"""Numerical acceptance for proportional fixed-temperature live-current updates."""
import copy
import json
import math
import time

import numpy as np
import pytest

from quick_pi_plugin.live_current import LiveCurrentError, LiveCurrentModel, live_current_eligibility
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import combine, strip


def bundle(mesh, result, request, terminal_units=None):
    value = {'model': '2.5D DC copper conduction; layered sheets and plated barrels',
             'request': request, 'mesh': mesh, 'result': result}
    if terminal_units is not None:
        value['terminal_units'] = terminal_units
    return value


def near(actual, expected, *, rtol=2e-8, atol=2e-11):
    np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol)


def compare_fields(actual, fresh):
    for key in ('potential_V', 'cell_J_A_mm2', 'cell_sheet_current_A_mm', 'cell_power_W'):
        a, b = actual[key], fresh[key]
        assert [row is None for row in a] == [row is None for row in b]
        near([row for row in a if row is not None], [row for row in b if row is not None])
    for key in ('source_current_A', 'sink_current_A', 'total_sink_current_A', 'sink_voltage_V',
                'voltage_drop_V', 'drop_over_current_ohm', 'V_over_I_ohm', 'total_power_W',
                'conductor_power_W', 'planar_power_W', 'via_power_W',
                'max_current_density_A_mm2', 'current_balance_error_A', 'max_nodal_residual_A',
                'energy_relative_error'):
        near(actual[key], fresh[key], atol=5e-10)
    assert actual['negative_sink_voltage'] == fresh['negative_sink_voltage']
    for got, expected in zip(actual['sinks'], fresh['sinks']):
        for key in ('current_A', 'voltage_V', 'voltage_drop_V'):
            near(got[key], expected[key])
        assert got['within_voltage_limits'] == expected['within_voltage_limits']
    for got, expected in zip(actual['vias'], fresh['vias']):
        for key in ('current_A', 'current_density_A_mm2', 'power_W'):
            if expected[key] is None:
                assert got[key] is None
            else:
                near(got[key], expected[key])
        assert got['thermal']['status'] == expected['thermal']['status']
        for key in ('energy_budget_J', 'time_to_limit_s', 'energy_ratio', 'adiabatic_temperature_c'):
            if expected['thermal'].get(key) is None:
                assert got['thermal'].get(key) is None
            else:
                near(got['thermal'][key], expected['thermal'][key])
    for got, expected in zip(actual['cell_thermal'], fresh['cell_thermal']):
        assert got['status'] == expected['status']
        for key in ('energy_budget_J', 'time_to_limit_s', 'energy_ratio', 'adiabatic_temperature_c'):
            if expected.get(key) is None:
                assert got.get(key) is None
            else:
                near(got[key], expected[key])
    assert actual['feasibility']['status'] == fresh['feasibility']['status']
    assert actual['feasibility']['violations'] == fresh['feasibility']['violations']
    assert actual['feasibility']['source_current_limit_exceeded'] == fresh['feasibility']['source_current_limit_exceeded']
    if fresh['feasibility']['source_current_headroom_A'] is not None:
        near(actual['feasibility']['source_current_headroom_A'],
             fresh['feasibility']['source_current_headroom_A'])
    for key in ('planar_W', 'via_W', 'component_W', 'package_W', 'total_W', 'accounting_error_W'):
        near(actual['analytics']['losses'][key], fresh['analytics']['losses'][key], atol=5e-10)
    for got, expected in zip(actual['analytics']['layers'], fresh['analytics']['layers']):
        near(got['planar_power_W'], expected['planar_power_W'])
        if expected['peak_current_density_A_mm2'] is not None:
            near(got['peak_current_density_A_mm2'], expected['peak_current_density_A_mm2'])
    for key in ('hotspots_by_current_density', 'hotspots_by_heating_density'):
        # Equal-valued mesh cells can exchange rank after fresh factorization
        # because of roundoff; compare the ranked physical values, not cell IDs.
        for field in ('current_density_A_mm2', 'power_W', 'power_density_W_mm3'):
            near([row[field] for row in actual['analytics'][key]],
                 [row[field] for row in fresh['analytics'][key]])


def test_single_sink_via_and_adiabatic_fields_match_fresh_solves():
    first, source, joined = strip()
    second, second_source, second_sink = strip(z=1.6)
    mesh, offset = combine(first, second)
    mesh['vias'] = [{'id': 'V1', 'top_nodes': joined,
                     'bottom_nodes': [index + offset for index in second_source],
                     'length_mm': 1.6, 'drill_mm': .3, 'plating_mm': .025}]
    sink = [index + offset for index in second_sink]
    options = {'pulse_duration_s': .02, 'ambient_c': 25, 'temperature_limit_c': 85}
    request = {'action': 'solve', 'source_voltage': 3.3, 'sink_current': 1.,
               'source_terminal': 'J1.1', 'sink_terminal': 'U1.1', 'options': options}
    original = bundle(mesh, solve(mesh, source, sink, source_voltage=3.3,
                                  sink_current=1., options=options), request)
    untouched = copy.deepcopy(original)
    model = LiveCurrentModel(original)
    assert model.base_current_A == 1.
    for current in (.1, .5, 1., 2., 8.):
        live = model.update(current)
        fresh = solve(mesh, source, sink, source_voltage=3.3,
                      sink_current=current, options=options)
        compare_fields(live['result'], fresh)
        assert live['request']['sink_current'] == current
        json.dumps(live, allow_nan=False)
    assert original == untouched
    assert model.update(1.)['result']['total_power_W'] == pytest.approx(original['result']['total_power_W'])


def test_proportional_multisink_limits_and_grouped_units_match_fresh_solves():
    first, source_a, sink_a = strip()
    second, source_b, sink_b = strip(length=20, width=2, z=1)
    mesh, offset = combine(first, second)
    source = source_a + [index + offset for index in source_b]
    electrodes = [sink_a, [index + offset for index in sink_b]]
    specs = [{'nodes': electrodes[0], 'id': 'A', 'label': 'Load A', 'current_A': 1.,
              'min_voltage_V': 3.29},
             {'nodes': electrodes[1], 'id': 'B', 'label': 'Load B', 'current_A': 2.,
              'min_voltage_V': 3.29, 'max_voltage_V': 3.299}]
    request = {'action': 'solve', 'source_voltage': 3.3, 'source_terminals': ['J1.1', 'J1.2'],
               'sinks': [{'terminals': ['U1.1', 'U1.2'], 'id': 'A', 'current_A': 1., 'min_voltage_V': 3.29},
                         {'terminal': 'U2.1', 'id': 'B', 'current_A': 2.,
                          'min_voltage_V': 3.29, 'max_voltage_V': 3.299}],
               'source_current_limit': 3.5}
    units = {'source_terminals': ['source-a', 'source-b'],
             'loads': [{'id': 'A', 'terminals': ['a', 'b'], 'current_A': 1.},
                       {'id': 'B', 'terminals': ['c'], 'current_A': 2.}]}
    base = solve(mesh, source, sinks=specs, source_voltage=3.3, source_current_limit=3.5)
    original = bundle(mesh, base, request, units)
    untouched = copy.deepcopy(original)
    model = LiveCurrentModel(original)
    for total in (.3, 1.5, 3., 6., 12.):
        factor = total / 3.
        live = model.update(total)
        fresh = solve(mesh, source, sinks=[dict(row, current_A=row['current_A'] * factor)
                                           for row in specs], source_voltage=3.3,
                      source_current_limit=3.5)
        compare_fields(live['result'], fresh)
        assert [row['current_A'] for row in live['request']['sinks']] == pytest.approx([factor, 2 * factor])
        assert [row['current_A'] for row in live['terminal_units']['loads']] == pytest.approx([factor, 2 * factor])
        assert live['request']['sinks'][0]['terminals'] == ['U1.1', 'U1.2']
        assert live['terminal_units']['loads'][0]['terminals'] == ['a', 'b']
    assert original == untouched


@pytest.mark.parametrize('change,reason', [
    (lambda row: row['request'].update(model_dimension='3d'), '2.5D'),
    (lambda row: row['request'].update(load_resistance_ohm=10), 'Resistive'),
    (lambda row: row['request'].update(sweep={'points': 3}), 'sweep'),
    (lambda row: row['request'].update(series=[{'r': 1}]), 'Series'),
    (lambda row: row['request'].update(package_conduction={'enabled': True}), 'Package'),
    (lambda row: row['request'].update(electrothermal=True), 'electrothermal'),
    (lambda row: row['request'].update(shared_return=True), 'Return-path'),
    (lambda row: row['mesh'].update(lumped_branches=[{'resistance_ohm': 1}]), 'Series'),
])
def test_unsupported_cases_are_explained(change, reason):
    mesh, source, sink = strip()
    value = bundle(mesh, solve(mesh, source, sink),
                   {'action': 'solve', 'sink_current': 1., 'source_terminal': 'J1.1',
                    'sink_terminal': 'U1.1'})
    change(value)
    eligible, explanation = live_current_eligibility(value)
    assert not eligible and reason.lower() in explanation.lower()
    with pytest.raises(LiveCurrentError, match=reason):
        LiveCurrentModel(value)


def test_invalid_updates_and_no_solver_on_update(monkeypatch):
    mesh, source, sink = strip(nx=80, ny=25)
    base = bundle(mesh, solve(mesh, source, sink),
                  {'action': 'solve', 'sink_current': 1., 'source_terminal': 'J1.1',
                   'sink_terminal': 'U1.1'})
    model = LiveCurrentModel(base)
    for invalid in (0, -1, float('nan'), float('inf'), True, None, 'bad'):
        with pytest.raises(LiveCurrentError):
            model.update(invalid)
    import quick_pi_plugin.solver as solver_module
    monkeypatch.setattr(solver_module, 'solve', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('solved again')))
    started = time.perf_counter()
    output = model.update(2.)
    elapsed = time.perf_counter() - started
    assert len(output['result']['cell_power_W']) == len(base['result']['cell_power_W'])
    assert output['result']['total_power_W'] == pytest.approx(4 * base['result']['total_power_W'])
    assert math.isfinite(elapsed)


def test_live_views_keep_current_dependent_results_independent():
    mesh, source, sink = strip(nx=8, ny=3)
    model = LiveCurrentModel(bundle(
        mesh, solve(mesh, source, sink),
        {'action': 'solve', 'sink_current': 1., 'source_terminal': 'J1.1', 'sink_terminal': 'U1.1'}))
    first = model.update(.5)
    second = model.update(2.)
    original_power = second['result']['cell_power_W'][0]
    original_feasible = second['result']['feasibility']['feasible']
    first['result']['cell_power_W'][0] = 0.
    first['result']['feasibility']['feasible'] = not original_feasible
    first['result']['analytics']['losses']['total_W'] = 0.
    first['result']['cell_thermal'][0]['status'] = 'changed'
    assert second['result']['cell_power_W'][0] == original_power
    assert second['result']['feasibility']['feasible'] == original_feasible
    assert second['result']['analytics']['losses']['total_W'] > 0.
    assert second['result']['cell_thermal'][0]['status'] != 'changed'
    assert model.update(2.)['result']['cell_power_W'][0] == original_power


def test_live_vectors_remain_json_compatible():
    import json
    mesh, source, sink = strip(nx=8, ny=3)
    model = LiveCurrentModel(bundle(
        mesh, solve(mesh, source, sink),
        {'action': 'solve', 'sink_current': 1., 'source_terminal': 'J1.1', 'sink_terminal': 'U1.1'}))
    live = model.update(1.5)
    decoded = json.loads(json.dumps(live))
    for key in ('cell_J_A_mm2', 'cell_sheet_current_A_mm'):
        np.testing.assert_allclose(decoded['result'][key], live['result'][key])
