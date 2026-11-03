"""Discovered routes remain editable, grouped and model-free until reviewed."""
from copy import deepcopy
import json
import pytest

from wayricad_runtime.series_topology import infer_series_paths
from quick_pi_plugin.series_inference import reviewed_path
from quick_pi_plugin.series_editor import parse_saved_path


from quick_pi_plugin.tests.series_inference_fixture import inventory


def selections(route):
    return [[dict(footprint_uuid=p['footprint_uuid'], model='100m' if i == 0 else '200m')
             for i,p in enumerate(stage['parts'])] for stage in route['stages']]


def test_infers_complete_route_parallel_banks_and_all_current_pins_without_models():
    chosen = inventory(); original = deepcopy(chosen)
    proposal = infer_series_paths(chosen, 'J1.1', 'J2.1')
    assert chosen == original
    route = proposal['routes'][0]
    assert route['nets'] == ['VIN','MID','OUT']
    assert [[p['reference'] for p in s['parts']] for s in route['stages']] == [['Q1','Q2'],['Q3','Q4']]
    assert all('model' not in p for s in route['stages'] for p in s['parts'])
    assert all(p['excluded_pads'] == [p['reference']+'-5'] for s in route['stages'] for p in s['parts'])
    path = reviewed_path(proposal, 0, selections(route), chosen)
    result = parse_saved_path(json.loads(json.dumps(path)), chosen)
    assert result['source_terminals'] == ['J1-1','J1-2']
    assert result['sink_terminals'] == ['J2-1','J2-2']
    pins = result['source_terminals'] + result['sink_terminals']
    for stage in result['series']:
        assert len(stage['parallel']) == 1
        for p in [stage, *stage['parallel']]:
            assert len(p['from_pads']) == len(p['to_pads']) == 2
            pins += p['from_pads'] + p['to_pads']
    assert len(set(pins)) == len(pins) == 20
    assert all(not p.endswith('-5') for p in pins)


def test_review_requires_values_and_keeps_user_pin_subsets():
    chosen = inventory(); proposal = infer_series_paths(chosen,'J1.1','J2.1')
    selected = selections(proposal['routes'][0])
    selected[1][1]['model'] = ''
    with pytest.raises(ValueError, match='Q4'):
        reviewed_path(proposal,0,selected,chosen)
    selected[1][1]['model'] = '150m+10nH'
    selected[0][0]['from_pads'] = ['Q1-2']
    path = reviewed_path(proposal,0,selected,chosen)
    assert path['branches'][0]['from_pads'] == ['Q1-2']
    assert parse_saved_path(path,chosen)['series'][1]['parallel'][0]['inductance_h'] == 1e-8
    selected[0][0]['from_pads'] = ['Q1-5']
    with pytest.raises(ValueError,match='pins'):
        reviewed_path(proposal,0,selected,chosen)


def test_discovery_lists_alternatives_and_explicitly_bounds_search():
    chosen = inventory()
    # A shorter alternative is offered separately, never silently substituted.
    for n,net in enumerate(['VIN','OUT'],1):
        chosen['terminals'].append(dict(id=f'R1-{n}',label=f'R1.{n}',reference='R1',footprint_uuid='r1',net=net))
    answer = infer_series_paths(chosen,'J1.1','J2.1')
    assert answer['routes'][0]['nets'] == ['VIN','OUT']
    assert any(r['nets'] == ['VIN','MID','OUT'] for r in answer['routes'])
    assert infer_series_paths(chosen,'J1.1','J2.1',max_routes=1)['truncated']
    assert infer_series_paths(chosen,'J1.1','J2.1',max_stages=1)['truncated']
    assert infer_series_paths(chosen,'J1.1','J2.1',max_expansions=1)['truncated']


def test_capacitor_and_unknown_device_are_not_assumed_to_conduct_dc():
    chosen = inventory()
    for row in chosen['terminals']:
        if row['reference'] in ('Q1','Q2'):
            row['reference'] = row['reference'].replace('Q','C')
            row['label'] = row['label'].replace('Q','C')
    assert not infer_series_paths(chosen,'J1.1','J2.1')['routes']
    assert infer_series_paths(chosen,'J1.1','J2.1',include_unknown=True)['routes']


def test_duplicate_id_or_ambiguous_pad_label_cannot_select_an_arbitrary_instance():
    chosen=inventory(); chosen['terminals'].append(deepcopy(chosen['terminals'][0]))
    with pytest.raises(ValueError,match='unique'):
        infer_series_paths(chosen,'J1.1','J2.1')
    chosen['terminals'][-1]['id']='different'
    with pytest.raises(ValueError,match='unambiguous'):
        infer_series_paths(chosen,'J1.1','J2.1')


def test_same_net_needs_no_series_and_disconnected_is_empty():
    chosen=inventory()
    assert infer_series_paths(chosen,'J1.1','J1.2')['routes'][0]['stages'] == []
    chosen['terminals'][-1]['net']='ISOLATED'
    assert not infer_series_paths(chosen,'J1.1','J2.2')['routes']


def test_pi_cli_discovery_protects_board_and_rejects_changed_source(tmp_path,monkeypatch):
    import hashlib
    from quick_pi_plugin.cli import main
    from quick_pi_plugin import service
    board=tmp_path/'Example.kicad_pcb'; board.write_text('unchanged',encoding='utf-8')
    chosen=inventory(); chosen['source_sha256']=hashlib.sha256(board.read_bytes()).hexdigest()
    monkeypatch.setattr(service,'run_job',lambda *a,**k:chosen)
    output=tmp_path/'candidates.json'
    args=[str(board),'--infer-series','--source','J1.1','--sink','J2.1','--output',str(output)]
    assert main(args)==0
    assert json.loads(output.read_bytes())['routes'][0]['nets']==['VIN','MID','OUT']
    assert main([*args[:-1],str(board)])==2
    assert board.read_text(encoding='utf-8')=='unchanged'
    assert main([*args,'--current','2'])==2
    chosen['source_sha256']='0'*64
    assert main(args)==2


def test_rlc_discovery_uses_shared_routes_and_rejects_source_change(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from trace_impedance_plugin import cli,measurement
    import wayricad_runtime.series_topology as topology
    board=tmp_path/'Example.kicad_pcb'; board.write_text('before',encoding='utf-8')
    monkeypatch.setitem(sys.modules,'pcbnew',SimpleNamespace(LoadBoard=lambda p:object()))
    monkeypatch.setattr(measurement,'TraceMeasurementEngine',lambda b:object())
    monkeypatch.setattr(topology,'board_inventory',lambda b:inventory())
    args=cli.parser().parse_args(['infer-series',str(board),'--start','J1.1','--end','J2.1'])
    assert cli.analyze(args)['result']['routes'][0]['nets']==['VIN','MID','OUT']
    def changed(_):
        board.write_text('changed',encoding='utf-8')
        return inventory()
    monkeypatch.setattr(topology,'board_inventory',changed)
    with pytest.raises(ValueError,match='changed'):
        cli.analyze(args)
