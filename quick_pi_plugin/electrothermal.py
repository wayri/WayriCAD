"""Steady DC/board-temperature fixed point with conservative heat transfer.

All geometry is in the saved board's millimetre frame. This module depends only
on Quick PI and the thermal kernel vendored in wayricad_runtime.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from dataclasses import replace

from .solver import solve, SolverError
from wayricad_runtime.thermal_multilayer import (
    DistributedHeatSource, prepare_distributed_sources, solve_multilayer_thermal,
)


class ElectrothermalError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _number(value, name, low=None, high=None):
    if isinstance(value, bool):
        raise ElectrothermalError('invalid_settings', name + ' requires a finite number.')
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ElectrothermalError('invalid_settings', name + ' requires a finite number.') from exc
    if not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ElectrothermalError('invalid_settings', name + ' is outside its valid range.')
    return value


def solve_electrothermal(request, cancel=None):
    """Solve request schema 1; invalid inputs raise, bounded stops are explicit.

    Required: mesh, source_nodes, sinks, thermal_geometry, thermal_settings,
    coupling.material_temperature_range_c. Optional component powers use the
    existing thermal_view/thermal_result records. Branch mappings declare a
    physical layer and convex polygon_mm contact. Via mappings declare their
    XY point, adjacent top_layer/bottom_layer and policy='uniform_axial'.
    """
    if not isinstance(request, Mapping) or request.get('schema_version', 1) != 1:
        raise ElectrothermalError('invalid_request', 'Expected electrothermal request schema_version 1.')
    request = copy.deepcopy(dict(request))
    def cancelled():
        if cancel and cancel():
            raise InterruptedError('Electrothermal solve cancelled; partial coupled results invalidated.')
    cancelled()
    try:
        mesh, geometry = request['mesh'], request['thermal_geometry']
        settings = request['thermal_settings']
        coupling = request['coupling']
        valid_range = coupling['material_temperature_range_c']
    except (KeyError, TypeError) as exc:
        raise ElectrothermalError('invalid_request', 'Mesh, thermal geometry/settings and an explicit material temperature range are required.') from exc
    for identity in ('source_sha256', 'stackup_sha256', 'variant'):
        supplied = [obj[identity] for obj in (request, mesh, geometry) if obj.get(identity) is not None]
        if supplied and any(value != supplied[0] for value in supplied):
            raise ElectrothermalError('source_mismatch', 'Electrical and thermal ' + identity + ' bindings differ.')
    if not isinstance(valid_range, (list, tuple)) or len(valid_range) != 2:
        raise ElectrothermalError('invalid_material', 'material_temperature_range_c requires [minimum, maximum].')
    minimum = _number(valid_range[0], 'Minimum material temperature', -273.15)
    maximum = _number(valid_range[1], 'Maximum material temperature', minimum)
    if maximum <= minimum:
        raise ElectrothermalError('invalid_material', 'Material temperature bounds must increase.')
    ambient = _number(settings.get('ambient_c', request.get('thermal_result', {}).get('ambient_c', 20)), 'Ambient', minimum, maximum)
    cap = _number(coupling.get('temperature_cap_c', min(150, maximum)), 'Temperature cap', ambient, maximum)
    relaxation = _number(coupling.get('relaxation', .5), 'Relaxation', 1e-6, 1)
    t_tol = _number(coupling.get('temperature_tolerance_c', .01), 'Temperature tolerance', 1e-12)
    p_tol = _number(coupling.get('loss_relative_tolerance', 1e-5), 'Relative loss tolerance', 0)
    p_abs = _number(coupling.get('loss_absolute_tolerance_w', 1e-8), 'Absolute loss tolerance', 0)
    max_iterations = coupling.get('max_iterations', 60)
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or not 1 <= max_iterations <= 1000:
        raise ElectrothermalError('invalid_settings', 'max_iterations must be an integer from 1 to 1000.')
    options = dict(request.get('electrical_options', {}))
    if 'triangle_temperature_c' in options or 'via_temperature_c' in options:
        raise ElectrothermalError('invalid_settings', 'Coupling owns the per-element temperature arrays.')
    options.update(temperature_c=ambient, ambient_c=ambient, material_temperature_range_c=[minimum, maximum])
    # Preserve the PI adiabatic screen as a separate diagnostic from coupling limits.
    if options.get('temperature_limit_c', 150) <= ambient:
        options['temperature_limit_c'] = ambient + 1
    thermal_result = dict(request.get('thermal_result', {}))
    thermal_result.setdefault('ambient_c', ambient)
    thermal_result.setdefault('environment', 'air')
    thermal_result.setdefault('components', [])
    view = request.get('thermal_view', {'components': []})
    component_refs = [str(row['reference']) for row in thermal_result['components']]
    if len(set(component_refs)) != len(component_refs):
        raise ElectrothermalError('duplicate_power', 'Component powers must have unique reference identities.')
    def electrical(triangle_t, via_t):
        cancelled()
        trial = dict(options, triangle_temperature_c=triangle_t, via_temperature_c=via_t)
        try:
            return solve(mesh, request['source_nodes'], sinks=request['sinks'],
                         source_voltage=request.get('source_voltage_V', 1.0),
                         source_current_limit=request.get('source_current_limit_A'), options=trial)
        except SolverError as exc:
            raise ElectrothermalError('electrical_failure', str(exc)) from exc
    triangle_t = [ambient] * len(mesh['triangles'])
    via_t = [ambient] * len(mesh.get('vias', []))
    cold = electrical(triangle_t, via_t)
    sources, owners = [], []
    def add(source, owner):
        sources.append(source)
        owners.append(owner)
    thermal_layers = {row['id']: row for row in geometry['layers']}
    for index, (triangle, layer, power) in enumerate(zip(mesh['triangles'], cold['cell_layer'], cold['cell_power_W'])):
        if power is None:
            continue  # Floating copper retains unknown electrical results.
        if layer not in thermal_layers:
            raise ElectrothermalError('missing_mapping', 'Triangle ' + str(index) + ': unknown physical thermal layer.')
        declared = thermal_layers[layer]
        if any(abs(mesh['points_mm'][node][2]-declared['z_mm']) > 1e-6 for node in triangle):
            raise ElectrothermalError('source_mismatch', 'Triangle ' + str(index) + ': electrical and thermal layer Z differ.')
        if not math.isclose(mesh['triangle_thickness_mm'][index], declared['thickness_mm'], rel_tol=1e-6, abs_tol=1e-9):
            raise ElectrothermalError('source_mismatch', 'Triangle ' + str(index) + ': electrical and thermal copper thickness differ.')
        polygon = [mesh['points_mm'][node][:2] for node in triangle]
        add(DistributedHeatSource('triangle:' + str(index), 'planar', power, layer, polygon_mm=polygon), ('triangle', index, 1.0))
    layer_ids = [row['id'] for row in geometry['layers']]
    via_maps = request.get('via_heat_mappings', {})
    for index, via in enumerate(cold['vias']):
        if via['power_W'] is None:
            continue
        identifier = str(via['id'])
        mapping = via_maps.get(identifier)
        if mapping is None:
            raise ElectrothermalError('missing_mapping', identifier + ': declare an explicit via axial heat mapping.')
        if mapping.get('policy') != 'uniform_axial':
            raise ElectrothermalError('missing_mapping', identifier + ': supported via policy is uniform_axial.')
        ends = [mapping.get('top_layer'), mapping.get('bottom_layer')]
        if any(lid not in layer_ids for lid in ends) or abs(layer_ids.index(ends[1])-layer_ids.index(ends[0])) != 1:
            raise ElectrothermalError('missing_mapping', identifier + ': each via segment must span adjacent declared thermal layers.')
        segment = mesh['vias'][index]
        for end, key in zip(ends, ('top_nodes', 'bottom_nodes')):
            if any(abs(mesh['points_mm'][node][2]-thermal_layers[end]['z_mm']) > 1e-6 for node in segment[key]):
                raise ElectrothermalError('source_mismatch', identifier + ': via axial mapping does not match its electrical endpoint layer.')
        expected_length = abs(thermal_layers[ends[1]]['z_mm']-thermal_layers[ends[0]]['z_mm'])
        if not math.isclose(segment['length_mm'], expected_length, rel_tol=1e-6, abs_tol=1e-9):
            raise ElectrothermalError('source_mismatch', identifier + ': via length disagrees with its declared axial span.')
        for endpoint, layer in enumerate(ends):
            add(DistributedHeatSource('via:' + identifier + ':' + str(endpoint), 'via', via['power_W']*.5,
                                      layer, point_mm=[mapping['x_mm'], mapping['y_mm']]), ('via', index, .5))
    branch_maps = request.get('branch_heat_mappings', {})
    for index, branch in enumerate(cold['components']):
        if not branch['power_W']:
            continue
        identifier = str(branch['id'])
        mapping = branch_maps.get(identifier)
        if mapping is None:
            raise ElectrothermalError('missing_mapping', identifier + ': powered branch needs a reviewed physical heat contact.')
        ref = str(mapping.get('component_reference', identifier))
        if ref in component_refs:
            raise ElectrothermalError('duplicate_power', ref + ': branch loss and explicit component power would double count heat.')
        add(DistributedHeatSource('branch:' + identifier, 'branch', branch['power_W'], mapping['layer_id'],
                                  polygon_mm=mapping['polygon_mm']), ('branch', index, 1.0))
    try:
        prepared = prepare_distributed_sources(geometry, settings, sources, cancel=cancel)
    except ValueError as exc:
        raise ElectrothermalError('missing_mapping', str(exc)) from exc
    def thermal(electric):
        cancelled()
        current = []
        for source, (kind, index, fraction) in zip(sources, owners):
            watts = (electric['cell_power_W'][index] if kind == 'triangle' else
                     electric['vias'][index]['power_W'] if kind == 'via' else electric['components'][index]['power_W'])
            current.append(replace(source, power_w=watts*fraction))
        mapped = math.fsum(source.power_w for source in current)
        residual = mapped-electric['total_power_W']
        if abs(residual) > max(1e-12, abs(mapped)*1e-10):
            raise ElectrothermalError('transfer_imbalance', 'Integrated planar/via/branch watts failed conservative transfer.')
        try:
            result = solve_multilayer_thermal(geometry, view, thermal_result, settings,
                                             distributed_sources=current, prepared_sources=prepared, cancel=cancel)
        except ValueError as exc:
            code = 'missing_cooling' if 'no convection' in str(exc) or 'no heat rejection' in str(exc) else 'thermal_failure'
            raise ElectrothermalError(code, str(exc)) from exc
        if result['status'] != 'converged':
            raise ElectrothermalError('thermal_imbalance', 'Thermal boundary heat balance failed.')
        temperatures = [ambient]*len(triangle_t)
        via_temperatures = [0.0]*len(via_t)
        for row, (kind, index, fraction) in zip(result['distributed_sources'], owners):
            if kind == 'triangle':
                temperatures[index] = row['temperature_c']
            elif kind == 'via':
                via_temperatures[index] += fraction*row['temperature_c']
        for index, via in enumerate(electric['vias']):
            if via['power_W'] is None:
                via_temperatures[index] = ambient
        transfer = {'electrical_loss_w': electric['total_power_W'], 'mapped_loss_w': mapped,
                    'residual_w': residual, 'planar_w': electric['planar_power_W'],
                    'via_w': electric['via_power_W'], 'branch_w': electric['component_power_W'],
                    'component_input_w': math.fsum(float(c['power_w']) for c in thermal_result['components']),
                    'minimum_coverage_fraction': min((p['coverage_fraction'] for p in prepared), default=1.0)}
        return result, temperatures, via_temperatures, transfer
    history, previous_loss = [], None
    status, diagnostic = 'iteration_limit', 'Iteration cap reached; review cooling, material units, mesh density or relaxation.'
    hot = field = transfer = None
    for iteration in range(1, max_iterations+1):
        electric = cold if iteration == 1 else electrical(triangle_t, via_t)
        candidate, new_t, new_v, balance = thermal(electric)
        all_t = [value for layer in candidate['layers'] for row in layer['values_c'] for value in row if value is not None]
        change = max([abs(a-b) for a,b in zip(triangle_t+via_t, new_t+new_v)] or [0])
        loss_change = None if previous_loss is None else abs(electric['total_power_W']-previous_loss)
        history.append({'iteration': iteration, 'relaxation': relaxation, 'temperature_residual_c': change,
                        'loss_w': electric['total_power_W'], 'loss_change_w': loss_change,
                        'minimum_c': min(all_t), 'maximum_c': max(all_t),
                        'thermal_balance_residual_w': candidate['heat_balance']['residual_w'],
                        'transfer_residual_w': balance['residual_w'],
                        'electrical_energy_relative_error': electric['energy_relative_error']})
        if min(all_t) < minimum or max(all_t) > maximum:
            status, diagnostic = 'material_range_exceeded', 'Layer temperatures exceed the declared material validity range; review material law and cooling.'
            break
        if max(all_t) > cap:
            status, diagnostic = 'temperature_cap', 'Temperature cap reached; this is not a converged operating point. Review cooling and power.'
            break
        if loss_change is not None and change <= t_tol and loss_change <= p_abs + p_tol*abs(electric['total_power_W']):
            # Publish an electrical rerun at the accepted temperature, with a
            # fresh thermal solve and the remaining fixed-point residual recorded.
            final_electric = electrical(new_t, new_v)
            final_field, final_t, final_v, final_balance = thermal(final_electric)
            final_residual = max([abs(a-b) for a,b in zip(new_t+new_v, final_t+final_v)] or [0])
            final_max = max(layer['sampled_max_c'] for layer in final_field['layers'])
            final_min = min(layer['sampled_min_c'] for layer in final_field['layers'])
            final_loss_change = abs(final_electric['total_power_W']-electric['total_power_W'])
            if (final_residual <= t_tol and final_loss_change <= p_abs+p_tol*abs(final_electric['total_power_W'])
                    and minimum <= final_min and final_max <= min(cap, maximum)):
                status, diagnostic = 'converged', 'Temperature, loss and all energy balances satisfy the declared tolerances.'
                hot, field, transfer = final_electric, final_field, final_balance
                triangle_t, via_t = new_t, new_v
                history[-1]['final_temperature_residual_c'] = final_residual
                break
        triangle_t = [a+relaxation*(b-a) for a,b in zip(triangle_t,new_t)]
        via_t = [a+relaxation*(b-a) for a,b in zip(via_t,new_v)]
        previous_loss = electric['total_power_W']
    cancelled()
    converged = status == 'converged'
    return {'schema_version': 1, 'mode': 'steady_electrothermal', 'status': status,
            'converged': converged, 'diagnostic': diagnostic, 'mesh': mesh,
            'cold': cold, 'hot': hot, 'thermal': field, 'transfer_balance': transfer,
            'convergence': {'status': status, 'converged': converged, 'history': history,
                            'iterations': len(history), 'relaxation': relaxation,
                            'temperature_tolerance_c': t_tol, 'loss_relative_tolerance': p_tol,
                            'loss_absolute_tolerance_w': p_abs},
            'temperatures': {'triangle_c': triangle_t, 'via_c': via_t} if converged else None,
            'limits': {'material_temperature_range_c': [minimum, maximum], 'temperature_cap_c': cap,
                       'operating_point_valid': bool(converged and hot['feasibility']['operating_point_valid'])},
            'bindings': {key: request.get(key, geometry.get(key)) for key in ('source_sha256', 'stackup_sha256', 'variant')},
            'solver_versions': {'electrical': 'quick-pi-spatial-dc-1', 'thermal': 'quicktherm-distributed-fv-1', 'coupling': 1},
            'assumptions': ['Steady 2.5D DC with fixed thermal properties and a declared linear copper resistivity law.',
                            'Uniform axial via losses allocate half the segment heat to each adjacent layer; feedback uses the same weights.',
                            'Explicit branch resistances remain fixed; branch material temperature laws are not inferred.',
                            'Delivered load power is not board heat unless explicitly supplied as component dissipation.',
                            'Conductor temperatures are distinct from component junction temperatures.',
                            'Coverage includes only the declared electrical mesh, nets and return paths.',
                            'Thermal cell support and contacts remain approximate; unsupported geometric source mappings are rejected.']}
