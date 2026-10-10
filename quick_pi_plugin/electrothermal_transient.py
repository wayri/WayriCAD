"""Bounded lumped rail/thermal-RC coupling with persistent accepted states.

R(T)=Rref*(1+alpha*(T-Tref)); L/C and thermal R/C remain fixed. Each
exchange interval freezes electrical R at an iterated midpoint temperature.
Electrical BE substeps supply integrated resistor energy, never reactive
storage or numerical damping, to exact constant-average-power thermal steps.
Trials all start at the same accepted state; only a converged trial is accepted.
"""
from __future__ import annotations

import hashlib
import json
import math

try:
    from .wayricad_runtime.thermal_rc import advance_thermal_rc
except ImportError:
    from wayricad_runtime.thermal_rc import advance_thermal_rc

from .transient import (RailStateStepper, TransientError, _number, _request,
                        _timeline, _voltage_violations)

SCHEMA = 'wayricad.electrothermal-transient/v1'
MAX_THERMAL_NODES = 128
MAX_EXCHANGE_INTERVALS = 2000
MAX_WORK_STEPS = 250000
MAX_TRACE_VALUES = 1500000


class CouplingFailure(TransientError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _cancel(cancel):
    if cancel and cancel():
        raise InterruptedError('Electrothermal transient cancelled; no partial paired result is valid.')


def _identity(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise TransientError(label+' must be a nonempty string of at most 128 characters.')
    return value


def _normalize(request):
    extra = {'exchange_step_s', 'ambient_c', 'thermal_nodes', 'resistance_mappings', 'coupling'}
    if not isinstance(request, dict):
        raise TransientError('Electrothermal transient request must be an object.')
    rail = _request({key:value for key,value in request.items() if key not in extra})
    exchange = _number(request.get('exchange_step_s'), 'exchange_step_s', positive=True)
    if exchange/2 == 0 or not math.isfinite(rail['duration_s']/exchange) or rail['duration_s']/exchange > MAX_EXCHANGE_INTERVALS:
        raise TransientError('Thermal exchange duration/step exceeds its bounded interval count.')
    ambient = _number(request.get('ambient_c'), 'ambient_c')
    if ambient < -273.15:
        raise TransientError('Ambient temperature must be at least absolute zero.')
    raw = request.get('thermal_nodes')
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_THERMAL_NODES:
        raise TransientError(f'Define 1 to {MAX_THERMAL_NODES} explicit thermal nodes.')
    nodes = []; identifiers = set()
    keys = {'id','label','resistance_K_W','capacitance_J_K','initial_temperature_c',
            'initial_power_W','step_power_W','step_time_s','max_temperature_c'}
    for row in raw:
        if not isinstance(row, dict) or set(row)-keys:
            raise TransientError('Thermal nodes must use only the documented R/C, temperature and power fields.')
        node = {'id':_identity(row.get('id'), 'Thermal node id')}
        if node['id'] in identifiers:
            raise TransientError('Repeated thermal node identity: '+node['id'])
        identifiers.add(node['id'])
        node['label'] = row.get('label', node['id'])
        if not isinstance(node['label'], str) or len(node['label']) > 256:
            raise TransientError('Thermal node label must be a string of at most 256 characters.')
        for key in ('resistance_K_W','capacitance_J_K'):
            node[key] = _number(row.get(key), node['id']+': '+key, positive=True)
        for key in ('initial_power_W','step_power_W','step_time_s'):
            node[key] = _number(row.get(key), node['id']+': '+key, nonnegative=True)
        if node['step_time_s'] > rail['duration_s']:
            raise TransientError('Thermal power event lies outside the study duration.')
        node['initial_temperature_c'] = _number(row.get('initial_temperature_c'), 'Initial thermal-node temperature')
        if node['initial_temperature_c'] < -273.15:
            raise TransientError('Initial temperature must be at least absolute zero.')
        node['max_temperature_c'] = None if row.get('max_temperature_c') is None else _number(row['max_temperature_c'], 'Temperature limit')
        # Validate fixed thermal scales before any electrical work.
        try:
            advance_thermal_rc(node['initial_temperature_c'], ambient, node['resistance_K_W'],
                               node['capacitance_J_K'], 0., exchange)
        except (ValueError, ArithmeticError) as exc:
            raise TransientError(str(exc)) from exc
        nodes.append(node)
    elements = {'source':rail['source_resistance_ohm']}
    for row in rail['loads']:
        elements['path:'+row['id']] = row['path_resistance_ohm']
        elements['esr:'+row['id']] = row['esr_ohm']
    powered = {key for key,value in elements.items() if value > 0}
    raw = request.get('resistance_mappings')
    if not isinstance(raw, list) or len(raw) != len(powered):
        raise TransientError('Map every nonzero source/path/ESR resistor exactly once to an explicit thermal node.')
    laws = []; seen = set()
    law_keys = {'element_id','thermal_node_id','reference_temperature_c','alpha_per_K',
                'min_temperature_c','max_temperature_c'}
    for row in raw:
        if not isinstance(row, dict) or set(row) != law_keys:
            raise TransientError('Each resistance mapping requires its identity, thermal node and explicit bounded linear law.')
        element = row['element_id']; node_id = row['thermal_node_id']
        if not isinstance(element, str) or element not in powered or element in seen:
            raise TransientError('Unknown, zero-valued or repeated mapped resistor identity.')
        if not isinstance(node_id, str) or node_id not in identifiers:
            raise TransientError('Resistance mapping refers to an unknown thermal node.')
        seen.add(element)
        law = {'element_id':element, 'thermal_node_id':node_id}
        for key in ('reference_temperature_c','alpha_per_K','min_temperature_c','max_temperature_c'):
            law[key] = _number(row[key], element+': '+key)
        low, high, reference = law['min_temperature_c'], law['max_temperature_c'], law['reference_temperature_c']
        if low < -273.15 or high < low or not low <= reference <= high:
            raise TransientError('Resistance-law reference and valid temperature interval are inconsistent.')
        factors = [1+law['alpha_per_K']*(value-reference) for value in (low,high)]
        if any(not math.isfinite(value) or value <= 0 for value in factors):
            raise TransientError('Resistance law must remain positive throughout its declared temperature range.')
        node_index = next(index for index,node in enumerate(nodes) if node['id'] == node_id)
        if not low <= nodes[node_index]['initial_temperature_c'] <= high:
            raise TransientError('Initial thermal state lies outside a mapped resistance law range.')
        law['node_index'] = node_index
        laws.append(law)
    if seen != powered:
        raise TransientError('A nonzero dissipative resistor has no reviewed thermal mapping.')
    options = request.get('coupling', {})
    defaults = dict(max_iterations=40, temperature_tolerance_c=1e-7,
                    resistance_relative_tolerance=1e-8, relaxation=.8)
    if not isinstance(options, dict) or set(options)-set(defaults):
        raise TransientError('Unknown electrothermal coupling option.')
    options = {**defaults, **options}
    if type(options['max_iterations']) is not int or not 1 <= options['max_iterations'] <= 100:
        raise TransientError('Coupling iteration limit must be an integer from 1 to 100.')
    for key in ('temperature_tolerance_c','resistance_relative_tolerance','relaxation'):
        options[key] = _number(options[key], key, positive=True)
    if options['relaxation'] > 1:
        raise TransientError('Coupling relaxation must not exceed one.')
    return dict(**rail, exchange_step_s=exchange, ambient_c=ambient,
                thermal_nodes=nodes, resistance_mappings=laws, coupling=options), rail, elements


def _resistances(parameters, elements, temperature):
    result = dict(elements)
    for law in parameters['resistance_mappings']:
        value = temperature[law['node_index']]
        if not law['min_temperature_c'] <= value <= law['max_temperature_c']:
            raise CouplingFailure('MATERIAL_RANGE_EXCEEDED', 'Thermal node '+law['thermal_node_id']+
                                  ' left the valid temperature range for '+law['element_id']+'. Review heating, cooling and the material law.')
        resistance = elements[law['element_id']]*(1+law['alpha_per_K']*(value-law['reference_temperature_c']))
        if not math.isfinite(resistance) or resistance <= 0:
            raise CouplingFailure('INVALID_HOT_RESISTANCE', 'Temperature-dependent resistance is not finite and positive.')
        result[law['element_id']] = resistance
    return result


def _grids(parameters, step, exchange):
    events = {row['step_time_s'] for row in parameters['loads']} | {row['step_time_s'] for row in parameters['thermal_nodes']}
    boundaries = _timeline(parameters['duration_s'], exchange, events)
    timeline = _timeline(parameters['duration_s'], step, set(boundaries)|events)
    if len(boundaries)-1 > 2*MAX_EXCHANGE_INTERVALS+len(events):
        raise TransientError('Exchange timeline including events exceeds its resource bound.')
    return boundaries, timeline, events


def _halve_timeline(timeline):
    result = [timeline[0]]
    for left,right in zip(timeline,timeline[1:]):
        midpoint = left+(right-left)/2
        if not left < midpoint < right:
            raise TransientError('An actual electrical interval cannot be halved at floating-point resolution.')
        result.extend((midpoint,right))
    return result


def _grid_evidence(timeline):
    gaps = [right-left for left,right in zip(timeline,timeline[1:])]
    return dict(intervals=len(gaps),min_interval_s=min(gaps),max_interval_s=max(gaps),
                sha256=hashlib.sha256(json.dumps(timeline,separators=(',',':')).encode('utf-8')).hexdigest())


def _run(parameters, rail, elements, step, exchange, coupled, cancel, work, electrical_timeline=None):
    boundaries, timeline, events = _grids(parameters, step, exchange)
    if electrical_timeline is not None:
        timeline = electrical_timeline
    temperatures = [node['initial_temperature_c'] for node in parameters['thermal_nodes']]
    fixed_r = _resistances(parameters, elements, temperatures)
    stepper = RailStateStepper(rail, fixed_r); state = stepper.initial_state()
    samples = []; history = []
    electric = dict(source_energy_J=0.,load_energy_J=0.,resistive_loss_energy_J=0.,
                    backward_euler_numerical_dissipation_J=0.,energy_residual_J=0.,
                    energy_scale=0.,charge_scale=0.,charge_error=0.,
                    max_charge_residual_C=0.,max_kvl_residual_V=0.)
    absolute_residual = 0.; thermal_input = ambient_energy = thermal_stored = thermal_residual = 0.
    external_energy = mapped_energy = 0.; initial_energy = stepper.quantities(state)['stored']
    element_totals = {key:0. for key in elements}
    node_totals = [dict(id=node['id'],resistor_input_J=0.,external_input_J=0.,input_J=0.,
                       to_ambient_J=0.,stored_change_J=0.,absolute_residual_J=0.)
                   for node in parameters['thermal_nodes']]
    no_feedback = not coupled or all(law['alpha_per_K'] == 0 for law in parameters['resistance_mappings'])

    def external(time):
        return [node['initial_power_W'] if time < node['step_time_s'] else node['step_power_W']
                for node in parameters['thermal_nodes']]

    def losses(quantities):
        values = {'source':quantities['source_loss']}
        for index,row in enumerate(rail['loads']):
            values['path:'+row['id']] = float(quantities['path_loss'][index])
            values['esr:'+row['id']] = float(quantities['esr_loss'][index])
        return values

    def record(time, phase, state_value, temperature, active, powers=None):
        quantities = active.quantities(state_value)
        powers = external(time) if powers is None else powers
        heat = list(powers)
        resistor_power = losses(quantities)
        for law in parameters['resistance_mappings']:
            heat[law['node_index']] += resistor_power[law['element_id']]
        samples.append(dict(time=time,phase=phase,q=quantities,temperature=list(temperature),
                            thermal_power=heat,resistances={key:value for key,value in active.resistances.items()}))

    def apply_event(time, active):
        nonlocal state
        demand = list(state['requested_current_A'])
        for index,row in enumerate(rail['loads']):
            if time == row['step_time_s']:
                demand[index] = row['step_current_A']
        state = active.project_state(state, demand)
        record(time, 'step_after', state, temperatures, active)

    stepper.resistances = fixed_r
    record(0.,'initial',state,temperatures,stepper,
           [node['initial_power_W'] for node in parameters['thermal_nodes']])
    if 0. in events:
        apply_event(0., stepper)
    cursor = 1
    for start, end in zip(boundaries,boundaries[1:]):
        _cancel(cancel)
        interval_times = [start]
        while cursor < len(timeline) and timeline[cursor] <= end:
            interval_times.append(timeline[cursor]); cursor += 1
        if interval_times[-1] != end:
            raise TransientError('Electrical and thermal timelines lost a common event boundary.')
        elapsed = end-start; previous_temperature = list(temperatures); guess = list(temperatures)
        start_state = state
        for iteration in range(1, parameters['coupling']['max_iterations']+1):
            _cancel(cancel)
            resistance = fixed_r if no_feedback else _resistances(parameters,elements,
                [(a+b)/2 for a,b in zip(previous_temperature,guess)])
            active = RailStateStepper(rail,resistance); active.resistances = resistance
            trial_state = active.project_state(start_state)
            initial_trial = trial_state
            trial = []; energy_by_element = {key:0. for key in elements}
            interval_ledger = dict(electric)
            for key in interval_ledger: interval_ledger[key] = 0.
            residual_sum = 0.
            for left,right in zip(interval_times,interval_times[1:]):
                _cancel(cancel); work[0] += 1
                if work[0] > MAX_WORK_STEPS:
                    raise CouplingFailure('RESOURCE_LIMIT', 'Electrothermal iteration work exceeded its bound; increase steps or narrow the study.')
                trial_state, q, ledger = active.advance(trial_state,right-left)
                trial.append((right,trial_state,q))
                for key in electric:
                    if key.startswith('max_'):
                        interval_ledger[key] = max(interval_ledger[key],ledger[key])
                    else:
                        interval_ledger[key] += ledger[key]
                residual_sum += abs(ledger['energy_residual_J'])
                energy_by_element['source'] += ledger['source_loss_energy_J']
                for index,row in enumerate(rail['loads']):
                    energy_by_element['path:'+row['id']] += ledger['path_loss_energy_J'][index]
                    energy_by_element['esr:'+row['id']] += ledger['esr_loss_energy_J'][index]
            power = external(start)
            for law in parameters['resistance_mappings']:
                power[law['node_index']] += energy_by_element[law['element_id']]/elapsed
            updates = [advance_thermal_rc(previous_temperature[index],parameters['ambient_c'],
                        node['resistance_K_W'],node['capacitance_J_K'],power[index],elapsed)
                       for index,node in enumerate(parameters['thermal_nodes'])]
            proposed = [row['temperature_c'] for row in updates]
            _resistances(parameters,elements,proposed)  # Endpoints also obey material ranges.
            new_r = fixed_r if no_feedback else _resistances(parameters,elements,
                        [(a+b)/2 for a,b in zip(previous_temperature,proposed)])
            delta_t = max(abs(a-b) for a,b in zip(proposed,guess))
            delta_r = max(abs(new_r[key]-resistance[key])/max(abs(new_r[key]),abs(resistance[key]),1e-300)
                          for key in elements)
            if no_feedback or (delta_t <= parameters['coupling']['temperature_tolerance_c'] and
                               delta_r <= parameters['coupling']['resistance_relative_tolerance']):
                break
            guess = [a+parameters['coupling']['relaxation']*(b-a) for a,b in zip(guess,proposed)]
        else:
            raise CouplingFailure('COUPLING_NOT_CONVERGED', 'Electrothermal interval did not converge at '+str(end)+
                                  ' s. Review exchange step, cooling, material laws and iteration settings.')
        # All trial states and trial heat were discarded until this point.
        if resistance != stepper.resistances:
            record(start,'exchange_after',initial_trial,previous_temperature,active)
        for time, electrical_state, _ in trial:
            node_t = [advance_thermal_rc(previous_temperature[index],parameters['ambient_c'],
                      node['resistance_K_W'],node['capacitance_J_K'],power[index],time-start)['temperature_c']
                      for index,node in enumerate(parameters['thermal_nodes'])]
            record(time,'step_before' if time in events else 'sample',electrical_state,node_t,active,
                   external(start) if time in events else None)
        state = trial_state; temperatures = proposed; stepper = active
        for key in electric:
            if key.startswith('max_'): electric[key] = max(electric[key],interval_ledger[key])
            else: electric[key] += interval_ledger[key]
        absolute_residual += residual_sum
        mapped_energy += math.fsum(energy_by_element.values())
        for key in elements: element_totals[key] += energy_by_element[key]
        external_energy += elapsed*math.fsum(external(start))
        thermal_input += math.fsum(row['input_J'] for row in updates)
        ambient_energy += math.fsum(row['to_ambient_J'] for row in updates)
        thermal_stored += math.fsum(row['stored_change_J'] for row in updates)
        thermal_residual += math.fsum(abs(row['residual_J']) for row in updates)
        for index,update in enumerate(updates):
            node_totals[index]['external_input_J'] += elapsed*external(start)[index]
            for key in ('input_J','to_ambient_J','stored_change_J'):
                node_totals[index][key] += update[key]
            node_totals[index]['absolute_residual_J'] += abs(update['residual_J'])
        for law in parameters['resistance_mappings']:
            node_totals[law['node_index']]['resistor_input_J'] += energy_by_element[law['element_id']]
        history.append(dict(start_s=start,end_s=end,iterations=iteration,
                            method='direct_one_way' if no_feedback else 'relaxed_fixed_point',
                            temperature_change_c=0. if no_feedback else delta_t,
                            resistance_relative_change=delta_r,
                            thermal_average_power_W=list(power)))
        if end in events:
            apply_event(end,active)
    electric.update(energy_relative_error=absolute_residual/max(electric['energy_scale'],1e-300),
                    charge_relative_error=electric['charge_error']/max(electric['charge_scale'],1e-300),
                    initial_stored_energy_J=initial_energy,final_stored_energy_J=samples[-1]['q']['stored'])
    electric['balance_status'] = 'PASSED' if max(electric['energy_relative_error'],electric['charge_relative_error']) <= 1e-8 else 'FAILED'
    transfer_residual = mapped_energy-electric['resistive_loss_energy_J']
    thermal_scale = abs(thermal_input)+abs(ambient_energy)+abs(thermal_stored)
    combined = math.fsum((electric['source_energy_J'],external_energy,-electric['load_energy_J'],
                         -ambient_energy,-thermal_stored,-(electric['final_stored_energy_J']-initial_energy),
                         -electric['backward_euler_numerical_dissipation_J']))
    combined_scale = math.fsum(abs(value) for value in (electric['source_energy_J'],external_energy,
                     electric['load_energy_J'],ambient_energy,thermal_stored,
                     electric['final_stored_energy_J']-initial_energy,electric['backward_euler_numerical_dissipation_J']))
    checks = dict(electrical=electric,thermal=dict(input_J=thermal_input,external_input_J=external_energy,
                  resistor_input_J=mapped_energy,to_ambient_J=ambient_energy,stored_change_J=thermal_stored,
                  absolute_residual_J=thermal_residual,relative_residual=thermal_residual/max(thermal_scale,1e-300),
                  nodes=node_totals),resistor_energy_J=element_totals,
                  transfer_residual_J=transfer_residual,combined_energy_residual_J=combined,
                  combined_energy_relative_error=abs(combined)/max(combined_scale,1e-300),
                  coupling_converged=True,exchange_history=history,
                  electrical_grid=_grid_evidence(timeline),exchange_grid=_grid_evidence(boundaries))
    checks['balance_status'] = 'PASSED' if electric['balance_status']=='PASSED' and checks['thermal']['relative_residual'] <= 1e-8 and abs(transfer_residual)/max(abs(mapped_energy),1e-300) <= 1e-10 and checks['combined_energy_relative_error'] <= 1e-8 else 'FAILED'
    return _trace(parameters,samples,checks)


def _trace(parameters,samples,checks):
    times = [row['time'] for row in samples]; violations = []; loads = []
    for index,row in enumerate(parameters['loads']):
        voltage = [float(sample['q']['voltage'][index]) for sample in samples]
        issues = _voltage_violations(voltage,times,row,parameters['source_voltage_V'])
        violations.extend(dict(load_id=row['id'],**issue) for issue in issues)
        result = dict(id=row['id'],label=row['label'],voltage_V=voltage,
                      min_voltage_V=min(voltage),max_voltage_V=max(voltage),violations=issues,
                      limits={key:row[key] for key in ('min_voltage_V','max_voltage_V')},within_voltage_limits=not issues)
        for field,key in (('capacitor_voltage_V','capacitor'),('current_A','current'),
                          ('requested_current_A','demand'),('path_loss_W','path_loss'),
                          ('esr_loss_W','esr_loss'),('load_power_W','load_power')):
            result[field] = [float(sample['q'][key][index]) for sample in samples]
        result['capacitor_current_A'] = [a-b for a,b in zip(result['current_A'],result['requested_current_A'])]
        loads.append(result)
    nodes = []
    for index,row in enumerate(parameters['thermal_nodes']):
        values = [sample['temperature'][index] for sample in samples]; issues = []
        limit = row['max_temperature_c']
        if limit is not None and max(values) > limit+1e-12*max(1.,abs(limit),max(abs(value) for value in values)):
            issues.append(dict(kind='maximum_temperature',limit_c=limit,observed_c=max(values),time_s=times[values.index(max(values))]))
            violations.extend(dict(thermal_node_id=row['id'],**issue) for issue in issues)
        nodes.append(dict(id=row['id'],label=row['label'],temperature_c=values,
                          power_W=[sample['thermal_power'][index] for sample in samples],
                          min_temperature_c=min(values),max_temperature_c=max(values),
                          limit_c=limit,within_temperature_limits=not issues,violations=issues,
                          energy_balance=checks['thermal']['nodes'][index]))
    source_current = [sample['q']['source_current'] for sample in samples]
    source_voltage = [sample['q']['source_voltage'] for sample in samples]
    limit = parameters['source_current_limit_A']; peak = max(source_current)
    exceeded = limit is not None and peak > limit+1e-12*max(abs(peak),abs(limit))
    if exceeded: violations.append(dict(kind='source_current_budget',limit_A=limit,observed_A=peak,time_s=times[source_current.index(peak)]))
    if min(source_voltage) < -1e-12*max(parameters['source_voltage_V'],max(abs(value) for value in source_voltage)):
        violations.append(dict(kind='negative_source_bus_voltage',limit_V=0.,observed_V=min(source_voltage),time_s=times[source_voltage.index(min(source_voltage))]))
    if checks['balance_status'] != 'PASSED': violations.append(dict(kind='numerical_balance_failure'))
    feasible = not violations
    initial = samples[0]['q']
    initial_rows = [dict(id=row['id'],current_A=float(initial['current'][index]),
                        voltage_V=float(initial['voltage'][index]),capacitor_voltage_V=float(initial['capacitor'][index]),
                        violations=_voltage_violations([float(initial['voltage'][index])],[0.],row,parameters['source_voltage_V']))
                    for index,row in enumerate(parameters['loads'])]
    initial_valid = (all(not row['violations'] for row in initial_rows) and initial['source_voltage'] >= 0 and
                     (limit is None or initial['source_current'] <= limit+1e-12*max(abs(limit),abs(initial['source_current']))) and
                     all(row['max_temperature_c'] is None or row['initial_temperature_c'] <= row['max_temperature_c']
                         for row in parameters['thermal_nodes']))
    return dict(times_s=times,sample_phase=[row['phase'] for row in samples],source_current_A=source_current,
                source_voltage_V=source_voltage,source_set_voltage_V=parameters['source_voltage_V'],
                source_power_W=[sample['q']['source_power'] for sample in samples],
                source_resistive_loss_W=[sample['q']['source_loss'] for sample in samples],
                total_resistive_loss_W=[sample['q']['loss'] for sample in samples],
                stored_energy_J=[sample['q']['stored'] for sample in samples],loads=loads,thermal_nodes=nodes,
                resistance_elements=[dict(element_id=key,resistance_ohm=[sample['resistances'][key] for sample in samples]) for key in samples[0]['resistances']],
                initialization=dict(method='pre_step_dc_at_explicit_initial_temperature',
                                    thermal_state='explicit_initial_temperature',
                                    feasible=initial_valid,source_current_A=initial['source_current'],
                                    source_voltage_V=initial['source_voltage'],loads=initial_rows),
                checks=checks,feasibility=dict(feasible=feasible,operating_point_valid=feasible,
                    status='FEASIBLE_REQUESTED_MODEL' if feasible else 'REQUESTED_LOAD_DIAGNOSTIC',
                    source_current_limit_mode='diagnostic_only',source_current_limit_A=limit,
                    source_current_limit_exceeded=exceeded,peak_source_current_A=peak,
                    source_current_headroom_A=None if limit is None else limit-peak,violations=violations))


def _comparison(coarse,fine,kind):
    matched = {(time,phase):index for index,(time,phase) in enumerate(zip(fine['times_s'],fine['sample_phase']))}
    pairs = []
    for index,key in enumerate(zip(coarse['times_s'],coarse['sample_phase'])):
        # Exchange discontinuities are numerical coefficient transitions. The
        # reference compares common physical samples/events and their extrema.
        if key[1] == 'exchange_after': continue
        if key not in matched:
            raise TransientError('Refinement omitted a shared physical sample or event.')
        pairs.append((index,matched[key]))
    if not pairs:
        raise TransientError('Refinement produced no shared physical sample points.')
    def maximum(a,b): return max(abs(a[i]-b[j]) for i,j in pairs)
    return dict(status='CHECKED_NOT_CERTIFIED',method=kind,comparison_samples=len(pairs),
                max_source_current_difference_A=maximum(coarse['source_current_A'],fine['source_current_A']),
                peak_source_current_difference_A=abs(max(coarse['source_current_A'])-max(fine['source_current_A'])),
                max_load_voltage_difference_V=max(maximum(a['voltage_V'],b['voltage_V']) for a,b in zip(coarse['loads'],fine['loads'])),
                max_temperature_difference_c=max(maximum(a['temperature_c'],b['temperature_c']) for a,b in zip(coarse['thermal_nodes'],fine['thermal_nodes'])),
                minimum_voltage_difference_V=max(abs(a['min_voltage_V']-b['min_voltage_V']) for a,b in zip(coarse['loads'],fine['loads'])),
                maximum_voltage_difference_V=max(abs(a['max_voltage_V']-b['max_voltage_V']) for a,b in zip(coarse['loads'],fine['loads'])),
                maximum_temperature_difference_c=max(abs(a['max_temperature_c']-b['max_temperature_c']) for a,b in zip(coarse['thermal_nodes'],fine['thermal_nodes'])),
                resistor_energy_difference_J=abs(coarse['checks']['electrical']['resistive_loss_energy_J']-fine['checks']['electrical']['resistive_loss_energy_J']),
                reference_balance_status=fine['checks']['balance_status'],
                control_feasible=coarse['feasibility']['feasible'],control_violations=coarse['feasibility']['violations'],
                reference_feasible=fine['feasibility']['feasible'],reference_violations=fine['feasibility']['violations'])


def solve_electrothermal_transient(request,cancel=None):
    """Return baseline/coupled traces or a failed diagnostic with no partial pair.

    Invalid request fields raise TransientError; cancellation raises
    InterruptedError. Nonconvergence and dynamic material-range failures return
    status=failed, coupled=None and feasible=False. Peaks/limits are sampled
    diagnostics; two independent step halvings are sensitivity evidence only.
    """
    if request.get('package_conduction') or request.get('electrical',{}).get('package_conduction'):
        raise ValueError('Explicit package contacts are unsupported in electrothermal rail transients.')
    if cancel is not None and not callable(cancel): raise TransientError('cancel must be callable or None.')
    _cancel(cancel)
    parameters,rail,elements = _normalize(request)
    public_parameters = {**parameters,'resistance_mappings':[
        {key:value for key,value in law.items() if key != 'node_index'}
        for law in parameters['resistance_mappings']]}
    grids = [_grids(parameters,step,exchange) for step,exchange in (
        (parameters['step_s'],parameters['exchange_step_s']),
        (parameters['step_s'],parameters['exchange_step_s']/2),
        (parameters['step_s']/2,parameters['exchange_step_s']))]
    # Exchange sensitivity uses a controlled pair with identical electrical
    # substeps. Primary traces keep their original grid for legacy compatibility.
    common_exchange_grid = _timeline(parameters['duration_s'],parameters['step_s'],
                                    set(grids[0][0])|set(grids[1][0])|grids[0][2])
    integration_grid = _halve_timeline(grids[0][1])
    sample_bound = len(grids[0][1])+len(grids[0][0])+len(grids[0][2])
    if 2*sample_bound*(9*len(rail['loads'])+2*len(parameters['thermal_nodes'])+len(elements)+8) > MAX_TRACE_VALUES:
        raise TransientError('Electrothermal paired output exceeds its scalar trace bound.')
    feedback = any(law['alpha_per_K'] != 0 for law in parameters['resistance_mappings'])
    estimated = (len(grids[0][1])-1)+(parameters['coupling']['max_iterations'] if feedback else 1)*sum(
        len(timeline)-1 for timeline in (grids[0][1],common_exchange_grid,common_exchange_grid,integration_grid))
    if estimated > MAX_WORK_STEPS:
        raise TransientError('Electrothermal integration/iteration/refinement work exceeds its bound; increase steps or narrow the study.')
    notice = ('Explicit lumped rail and independent thermal R/C-to-ambient nodes; no spatial transient, regulator control or CV/CC simulation. '
              'Current limits are diagnostic budgets; requested currents are never capped. '
              'Resistances use an iterated interval-midpoint temperature; fixed L/C store energy and are not heat. '
              'Only integrated physical source/path/ESR resistor energy and explicit external power heat thermal nodes. '
              'Backward Euler numerical damping is reported separately and is not transferred as heat. '
              'Independent exchange/integration step halvings report sensitivity, not certified peak accuracy.')
    work = [0]
    try:
        baseline = _run(parameters,rail,elements,parameters['step_s'],parameters['exchange_step_s'],False,cancel,work)
        coupled = _run(parameters,rail,elements,parameters['step_s'],parameters['exchange_step_s'],True,cancel,work)
        exchange_control = _run(parameters,rail,elements,parameters['step_s'],parameters['exchange_step_s'],
                                True,cancel,work,common_exchange_grid)
        exchange_ref = _run(parameters,rail,elements,parameters['step_s'],parameters['exchange_step_s']/2,
                            True,cancel,work,common_exchange_grid)
        integration_ref = _run(parameters,rail,elements,parameters['step_s']/2,parameters['exchange_step_s'],
                               True,cancel,work,integration_grid)
    except CouplingFailure as exc:
        return dict(schema=SCHEMA,status='failed',model='lumped_multisink_electrothermal_rlc_rc',notice=notice,
                    parameters=public_parameters,baseline=None,coupled=None,
                    checks=dict(coupling_converged=False,balance_status='UNVERIFIED',failure_code=exc.code),
                    feasibility=dict(feasible=False,operating_point_valid=False,status=exc.code,
                                     source_current_limit_mode='diagnostic_only',violations=[dict(kind=exc.code)]),
                    issues=[dict(code=exc.code,severity='error',message=str(exc))])
    refinement = dict(status='CHECKED_NOT_CERTIFIED',
        exchange=_comparison(exchange_control,exchange_ref,'half_exchange_step_common_electrical_grid'),
        integration=_comparison(coupled,integration_ref,'half_each_actual_electrical_interval_fixed_exchange_grid'),
        coarse_exchange_step_s=parameters['exchange_step_s'],coarse_electrical_step_s=parameters['step_s'],
        notice='Further independent refinements are required before relying on sampled extrema and operating limits.')
    refinement['exchange'].update(control_electrical_grid=exchange_control['checks']['electrical_grid'],
        reference_electrical_grid=exchange_ref['checks']['electrical_grid'],
        additional_control_intervals=exchange_control['checks']['electrical_grid']['intervals']-coupled['checks']['electrical_grid']['intervals'],
        control_exchange_grid=exchange_control['checks']['exchange_grid'],
        reference_exchange_grid=exchange_ref['checks']['exchange_grid'],
        notice='Both exchange runs use the same electrical grid containing coarse and half-exchange boundaries; the control grid can be finer than the primary trace.')
    refinement['integration'].update(control_electrical_grid=coupled['checks']['electrical_grid'],
        reference_electrical_grid=integration_ref['checks']['electrical_grid'],
        control_exchange_grid=coupled['checks']['exchange_grid'],reference_exchange_grid=integration_ref['checks']['exchange_grid'])
    reference_feasible = all(value['feasibility']['feasible'] for value in (exchange_control,exchange_ref,integration_ref))
    feasible = coupled['feasibility']['feasible'] and reference_feasible
    feasibility = {**coupled['feasibility'],'feasible':feasible,'operating_point_valid':feasible,
                   'refinement_reference_feasible':reference_feasible,
                   'baseline_feasible':baseline['feasibility']['feasible'],
                   'coupled_feasible':coupled['feasibility']['feasible']}
    peak = max(value['feasibility']['peak_source_current_A'] for value in (coupled,exchange_control,exchange_ref,integration_ref))
    limit = parameters['source_current_limit_A']
    feasibility.update(peak_source_current_A=peak,
                       source_current_headroom_A=None if limit is None else limit-peak,
                       source_current_limit_exceeded=any(value['feasibility']['source_current_limit_exceeded'] for value in
                                                        (coupled,exchange_control,exchange_ref,integration_ref)))
    if not feasible: feasibility['status']='REQUESTED_LOAD_DIAGNOSTIC'
    if not feasibility['refinement_reference_feasible']:
        feasibility['violations'] = [*feasibility['violations'],dict(kind='refinement_reference_violation')]
    balance = 'PASSED' if all(value['checks']['balance_status']=='PASSED' for value in
                             (baseline,coupled,exchange_control,exchange_ref,integration_ref)) else 'FAILED'
    return dict(schema=SCHEMA,status='completed',model='lumped_multisink_electrothermal_rlc_rc',notice=notice,
                parameters=public_parameters,baseline=baseline,coupled=coupled,feasibility=feasibility,issues=[],
                checks=dict(coupling_converged=True,balance_status=balance,
                            refinement=refinement,work_steps=work[0]))
