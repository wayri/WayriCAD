"""3D DC and board-grid feedback checks on a deterministic copper coupon."""
import json
import math

import pytest

from quick_pi_plugin.volume_joule import _thermal_projection, solve_volume_feedback


def coupon():
    outline = [[0, 0], [4, 0], [4, 4], [0, 4]]
    polygon = dict(outer=outline, holes=[])
    geometry = dict(
        outline_status='valid', outline=[dict(outer_mm=outline, holes_mm=[])],
        bbox_mm=[0, 0, 4, 4], barrels=[], mounting_holes=[],
        layers=[dict(id=0, name='F.Cu', z_mm=0, thickness_mm=.035, polygons_mm=[polygon]),
                dict(id=31, name='B.Cu', z_mm=1.6, thickness_mm=.035, polygons_mm=[polygon])],
    )
    mesh = {'points_mm': [[1, 1, 0], [3, 1, 0], [1, 3, 0], [1, 1, .017]],
            'tetrahedra': [[0, 1, 2, 3]], 'plating_mm': .025}
    feedback = {
        'thermal_settings': dict(ambient_c=20, dielectric_k_w_mk=.3, copper_k_w_mk=385,
                                 via_plating_mm=.025, grid_cells_long_axis=24,
                                 board_h_w_m2k=5, board_emissivity=.85),
        'coupling': dict(material_temperature_range_c=[0, 150], temperature_cap_c=105,
                         max_iterations=40, relaxation=.7),
    }
    return mesh, geometry, feedback


def test_coupled_tetrahedral_temperature_adjusts_resistance_and_balances_watts():
    mesh, geometry, feedback = coupon()
    result = solve_volume_feedback(mesh, [0, 2, 3], [1], geometry, feedback,
                                   source_voltage=3.3, sink_current=.8)
    info = result['joule_feedback']
    assert info['status'] == 'converged'
    assert result['solution_basis'] == 'coupled_steady'
    temperature, = result['element_temperature_c']
    assert temperature > 20
    expected_ratio = 1 + .00393 * (temperature - 20)
    ratio = result['drop_over_current_ohm'] / info['cold']['drop_over_current_ohm']
    assert math.isclose(ratio, expected_ratio, rel_tol=1e-10)
    assert math.isclose(result['total_power_W'], info['heat_balance']['input_w'], rel_tol=1e-10)
    assert abs(info['heat_balance']['residual_w']) < info['heat_balance']['tolerance_w']
    assert result['energy_relative_error'] < 1e-8
    json.dumps(result, allow_nan=False)


def test_temperature_limit_labels_and_retains_the_cold_only_reference():
    mesh, geometry, feedback = coupon()
    feedback['coupling']['temperature_cap_c'] = 20.01
    result = solve_volume_feedback(mesh, [0, 2, 3], [1], geometry, feedback,
                                   source_voltage=3.3, sink_current=.8)
    assert result['solution_basis'] == 'cold_baseline'
    assert result['joule_feedback']['status'] == 'temperature_cap'
    assert 'element_temperature_c' not in result
    assert result['voltage_drop_V'] == result['joule_feedback']['cold']['voltage_drop_V']


def test_gap_centroid_projects_to_both_layers_with_exact_unit_weight():
    import numpy as np
    _, geometry, feedback = coupon()
    projection = _thermal_projection(geometry, feedback['thermal_settings'], np.array([[2., 2., .8]]))
    sources, support, base, split, fraction, blend = projection
    assert [source.layer_id for source in sources] == [0, 31]
    assert list(base) == [0] and list(split) == [1] and list(blend) == [True]
    assert list(fraction) == pytest.approx([.5])
    assert all(row['coverage_fraction'] == 1 for row in support)

def test_stock_heating_runs_on_a_saved_native_coupon(tmp_path):
    pytest.importorskip('pcbnew')
    pytest.importorskip('gmsh')
    import hashlib
    from pathlib import Path
    from shutil import copyfile

    from quick_pi_plugin.service import execute

    source = Path(__file__).resolve().parents[2] / 'docs/examples/pocket-kivi/example.kicad_pcb'
    path = tmp_path / 'coupon.kicad_pcb'
    copyfile(source, path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    inventory = execute({'action': 'inspect', 'board_path': str(path)})
    signal = '/Front outputs/SLOT1'
    source_pad, load_pad = [row['id'] for row in inventory['terminals'] if row['net'] == signal]
    _, _, feedback = coupon()
    result = execute(dict(action='solve', board_path=str(path), net=signal, model_dimension='3d',
                          source_terminal=source_pad, sink_terminal=load_pad, sink_current=.25,
                          source_voltage=3.3, edge_mm=1., plating_mm=.025,
                          joule_feedback=feedback))['result']
    assert result['solution_basis'] == 'coupled_steady'
    assert result['joule_feedback']['converged']
    assert result['joule_feedback']['peak_temperature_c'] > 20
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_grouped_electrodes_keep_independent_load_currents_during_heating():
    mesh, geometry, feedback = coupon()
    mesh['points_mm'].append([3, 3, .017])
    mesh['tetrahedra'].append([1, 2, 3, 4])
    sinks = [dict(id='A', label='Grouped load', nodes=[1,4], current_A=.5),
             dict(id='B', label='Auxiliary load', nodes=[2], current_A=.2)]
    result = solve_volume_feedback(mesh, [0,3], None, geometry, feedback,
                                   source_voltage=3.3, sinks=sinks, source_current_limit=.6)
    assert result['solution_basis'] == 'coupled_steady'
    assert [row['current_A'] for row in result['sinks']] == [.5, .2]
    assert result['potential_V'][1] == result['potential_V'][4]
    assert result['potential_V'][0] == result['potential_V'][3] == 3.3
    assert result['potential_V'][1] != result['potential_V'][2]
    assert result['source_current_A'] == pytest.approx(.7)
    assert result['feasibility']['source_current_limit_exceeded']
    budget = math.fsum(row['current_A']*row['voltage_drop_V'] for row in result['sinks'])
    assert result['total_power_W'] == pytest.approx(budget)
    assert result['joule_feedback']['cold']['total_power_W'] < budget


def test_grid_preserves_drill_voids_and_exact_hole_membership():
    from wayricad_runtime.thermal_multilayer import _blocked_grid_links, _copper_probe, _polygon_contains

    outline = [[0,0],[4,0],[4,4],[0,4]]
    hole = [[1.9,1.8],[2.1,1.8],[2.1,2.2],[1.9,2.2]]
    polygon = {'outer':outline,'holes':[hole]}
    probe = _copper_probe(polygon)
    for point in ((1.,2.),(1.9,2.),(2.,2.),(2.1,2.),(3.,2.),(4.,2.),(4.1,2.)):
        assert probe(point) == _polygon_contains(point,polygon)
    links = _blocked_grid_links([{'outer_mm':outline,'holes_mm':[hole]}],
                                [1.,3.],[2.],{(0,0):0,(1,0):1})
    assert links == {((0,0),(1,0))}
