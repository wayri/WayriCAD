"""Power-tree accounting retains complete series and parallel pin topology."""
from copy import deepcopy
import json

import pytest

from quick_pi_plugin.series_inference import reviewed_path
from quick_pi_plugin.series_editor import parse_saved_path
from quick_pi_plugin.series_power_tree import build_series_power_tree, series_path_tree, tree_html, tree_text
from quick_pi_plugin.tests.series_inference_fixture import inventory
from wayricad_runtime.series_topology import infer_series_paths


def fixture():
    saved = inventory()
    proposal = infer_series_paths(saved, 'J1.1', 'J2.1')
    selections = [[dict(footprint_uuid=p['footprint_uuid'], model='100m' if i == 0 else '200m')
                   for i, p in enumerate(stage['parts'])] for stage in proposal['routes'][0]['stages']]
    path = reviewed_path(proposal, 0, selections, saved)
    request = parse_saved_path(path, saved)
    return saved, path, request


def solved_bundle():
    saved, path, request = fixture()
    branches, components = [], []
    for index, stage in enumerate(request['series']):
        for parallel, part in enumerate([stage, *stage['parallel']]):
            identifier = f'part-{index}-{parallel}'
            branches.append(dict(part, id=identifier))
            current = 4 / 3 if parallel == 0 else 2 / 3
            # Both banks carry 2 A; total copper loss is 0.1 W.
            before = 3.28 if index == 0 else 3.1366666666666667
            after = before - 2 / 15
            components.append(dict(id=identifier, current_A=current, voltage_before_V=before,
                                   voltage_after_V=after, voltage_drop_V=before-after, power_W=current*(before-after)))
    result = dict(source_voltage_V=3.3, source_current_A=2., sink_voltage_V=2.9833333333333334,
                  sink_current_A=2., components=components, feasibility=dict(feasible=True))
    return dict(request=request, geometry=saved, mesh=dict(lumped_branches=branches), result=result)


def test_inferred_draft_retains_all_segments_parallel_components_and_twenty_pins():
    saved, path, request = fixture(); original = deepcopy(path)
    tree = series_path_tree(path, saved)
    assert tree['status'] == 'topology_only'
    assert [n['net'] for n in tree['nodes'] if n['kind'] == 'copper'] == ['VIN', 'MID', 'OUT']
    banks = [n for n in tree['nodes'] if n['kind'] == 'parallel_stage']
    assert [[p['reference'] for p in n['parts']] for n in banks] == [['Q1','Q2'],['Q3','Q4']]
    pins = {p['id'] for n in tree['nodes'] for p in n.get('pins', [])}
    for bank in banks:
        for part in bank['parts']:
            assert len(part['incoming_pins']) == len(part['outgoing_pins']) == 2
            pins.update(p['id'] for p in part['incoming_pins'] + part['outgoing_pins'])
            assert part['efficiency_fraction'] is None
    assert len(pins) == 20 and all(not pin.endswith('-5') for pin in pins)
    assert path == original
    assert tree['summary']['input_power_W'] is None
    assert json.loads(json.dumps(tree, allow_nan=False)) == tree


def test_per_node_power_and_efficiency_conserve_without_equal_parallel_sharing():
    bundle = solved_bundle(); original = deepcopy(bundle)
    tree = build_series_power_tree(bundle)
    stages = [n for n in tree['nodes'] if n['kind'] == 'parallel_stage']
    copper = [n for n in tree['nodes'] if n['kind'] == 'copper']
    assert tree['summary']['input_power_W'] == pytest.approx(6.6)
    assert tree['summary']['output_power_W'] == pytest.approx(5.966666666666667)
    assert tree['summary']['loss_W'] == pytest.approx(sum(n['loss_W'] for n in stages + copper))
    assert sum(n['loss_W'] for n in copper) == pytest.approx(.1)
    assert stages[0]['parts'][0]['current_A'] == pytest.approx(4/3)
    assert stages[0]['parts'][1]['current_A'] == pytest.approx(2/3)
    for stage in stages:
        assert stage['current_A'] == pytest.approx(2.)
        assert stage['efficiency_fraction'] == pytest.approx(stage['output_power_W']/stage['input_power_W'])
    assert bundle == original


def test_incomplete_or_infeasible_operating_point_does_not_invent_efficiency():
    bundle = solved_bundle()
    bundle['result']['components'][0]['current_A'] = None
    tree = build_series_power_tree(bundle)
    bank = next(n for n in tree['nodes'] if n['kind'] == 'parallel_stage')
    assert bank['current_A'] is None and bank['loss_W'] is None and bank['efficiency_fraction'] is None
    bundle = solved_bundle(); bundle['result']['feasibility']['feasible'] = False
    tree = build_series_power_tree(bundle)
    assert tree['summary']['efficiency_fraction'] is None
    assert all(n.get('efficiency_fraction') is None for n in tree['nodes'])


def test_repeated_physical_net_keeps_topology_but_cannot_allocate_copper_occurrences():
    bundle = solved_bundle()
    for row in bundle['geometry']['terminals']:
        if row.get('net') == 'OUT':
            row['net'] = 'VIN'
    tree = build_series_power_tree(bundle)
    copper = [node for node in tree['nodes'] if node['kind'] == 'copper']
    assert [node['net'] for node in copper] == ['VIN', 'MID', 'VIN']
    for node in copper:
        assert node['accounting_status'] == 'unavailable_repeated_net'
        assert all(node[key] is None for key in ('current_A', 'loss_W', 'voltage_drop_V', 'input_power_W', 'efficiency_fraction'))
    assert tree['summary']['input_power_W'] == pytest.approx(6.6)
    assert next(node for node in tree['nodes'] if node['kind'] == 'parallel_stage')['parts'][0]['current_A'] == pytest.approx(4/3)
    assert 'Repeated physical nets' in tree_text(tree)


def test_text_and_offline_vector_report_include_nets_components_and_pin_numbers():
    tree = build_series_power_tree(solved_bundle())
    text = tree_text(tree); html = tree_html(tree)
    for name in ('VIN', 'MID', 'OUT', 'Q1.1', 'Q1.2', 'Q4.3', 'Q4.4', 'J1.2', 'J2.2'):
        assert name in text and name in html
    assert '<svg ' in html and 'loss ' in html and 'transmission ' in html
    assert build_series_power_tree(dict(request={})) is None
    assert tree_html(None) == ''


def test_pdf_diagram_uses_lossless_png_and_treats_net_names_as_literal_text():
    import base64
    import re
    pytest.importorskip('matplotlib')
    tree = build_series_power_tree(solved_bundle())
    tree['nodes'][1]['label'] = r'$\notacommand$'
    html = tree_html(tree, raster=True)
    images = re.findall(r'data:image/png;base64,([^\"]+)', html)
    assert len(images) == 1
    assert all(base64.b64decode(image).startswith(b'\x89PNG\r\n\x1a\n') for image in images)
