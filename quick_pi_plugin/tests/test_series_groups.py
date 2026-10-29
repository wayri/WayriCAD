"""Grouped series electrodes retain one model and total current, never gate pins."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import json
import pytest
from quick_pi_plugin.series_editor import parse_saved_path
from quick_pi_plugin.service import series_execute
from quick_pi_plugin.tests.test_solver import strip


def inventory():
    rows=[]
    for ref,pads in [('J1',[('s1','A'),('s2','A')]),('Q1',[('a1','A'),('a2','A'),('b1','B'),('b2','B'),('gate','G')]),
                     ('U1',[('e1','B'),('e2','B')])]:
        for number,(identifier,net) in enumerate(pads,1):
            rows.append({'id':identifier,'label':ref+'.'+str(number),'reference':ref,'net':net,'footprint_uuid':ref})
    return {'nets':['A','B','G'],'terminals':rows}


def saved_path():
    return {'schema':1,'source':'J1.1','sink':'U1.1','source_terminals':['s1','s2'],
        'sink_terminals':['e1','e2'],'branches':[{'reference':'Q1','from_pad':'a1','to_pad':'b1',
            'from_pads':['a1','a2'],'to_pads':['b1','b2'],'model':'100mΩ'}]}


def native_board():
    def pad(row):
        return NS(GetNetCode=lambda:1,m_Uuid=NS(AsString=lambda:row['id']),
                  GetNumber=lambda:row['label'].split('.')[1],GetNetname=lambda:row['net'])
    footprints=[]
    for reference in ('J1','Q1','U1'):
        pads=[pad(row) for row in inventory()['terminals'] if row['reference']==reference]
        footprints.append(NS(GetReference=lambda ref=reference:ref,m_Uuid=NS(AsString=lambda ref=reference:ref),Pads=lambda values=pads:values))
    return NS(GetFootprints=lambda:footprints)


def mesh_for(net):
    mesh,left,right=strip(nx=2,ny=1)
    mesh['mesh_sizing']={'mode':'manual'};mesh['mesh_report']=[]
    if net=='A':terminals={'s1':[left[0]],'s2':[left[1]],'a1':[right[0]],'a2':[right[1]]}
    else:terminals={'b1':[left[0]],'b2':[left[1]],'e1':[right[0]],'e2':[right[1]]}
    mesh['terminal_nodes']=terminals
    return mesh


def extract(board,net,**kwargs):
    return {'net':net,'terminals':[row for row in inventory()['terminals'] if row['net']==net],
        'layers':[{'id':0,'name':'F.Cu','polygons':[],'mesh_regions':[]}],'vias':[],'warnings':[], 'counts':{}}


def request():
    result=parse_saved_path(saved_path(),inventory())
    result.update(source_voltage=3.3,sink_current=2.)
    return result


def test_grouped_path_roundtrip_keeps_all_explicit_groups_and_total_current():
    data=saved_path();before=deepcopy(data)
    parsed=parse_saved_path(json.loads(json.dumps(data)),inventory())
    assert parsed['source_terminal']=='s1' and parsed['source_terminals']==['s1','s2']
    assert parsed['sink_terminal']=='e1' and parsed['sink_terminals']==['e1','e2']
    assert parsed['series'][0]['from_pads']==['a1','a2']
    assert parsed['series'][0]['to_pads']==['b1','b2']
    assert 'gate' not in json.dumps(parsed)
    assert data==before


def test_production_series_assembly_and_real_solver_use_whole_electrode_once():
    with patch('quick_pi_plugin.board_geometry.extract',side_effect=extract), \
         patch('quick_pi_plugin.mesh.build_mesh',side_effect=lambda geo,**kwargs:mesh_for(geo['net'])):
        bundle=series_execute(native_board(),Path('Example.kicad_pcb'),request())
    result=bundle['result'];branch=bundle['mesh']['lumped_branches'][0]
    assert len(branch['top_nodes'])==2 and len(branch['bottom_nodes'])==2
    assert result['sink_current_A']==pytest.approx(2.)
    assert result['components'][0]['current_A']==pytest.approx(2.)
    assert result['components'][0]['power_W']==pytest.approx(.4)
    strip_resistance=1.724e-8*.01/(.001*.000035)
    assert result['voltage_drop_V']==pytest.approx(2*(.1+2*strip_resistance),abs=1e-10)
    assert bundle['terminal_units']['loads'][0]['current_A']==2.
    assert bundle['terminal_units']['series'][0]['from_terminals']==['a1','a2']
    assert 'gate' not in bundle['mesh']['terminal_nodes']


@pytest.mark.parametrize('change,pattern', [
    (lambda data:data['branches'][0].update(from_pads=['a1','gate']),'one assigned net'),
    (lambda data:data['branches'][0].update(from_pads=['a1','s2']),'one exact component'),
    (lambda data:data['branches'][0].update(from_pads=['a1','Q1.1']),'aliases'),
    (lambda data:data.update(source_terminals=['s2']),'include its reviewed anchor'),
    (lambda data:data.update(sink_terminals=['e1','b1']),'one exact component')])
def test_grouped_path_rejects_control_net_wrong_owner_alias_and_anchor_omission(change,pattern):
    data=saved_path();change(data)
    with pytest.raises(ValueError,match=pattern):parse_saved_path(data,inventory())


def test_direct_service_revalidates_groups_before_loading_mesh_dependencies():
    value=request();value['series'][0]['from_pads']=['a1','gate']
    with patch('quick_pi_plugin.mesh.build_mesh') as build,pytest.raises(ValueError,match='one exact component and net'):
        series_execute(native_board(),Path('Example.kicad_pcb'),value)
    build.assert_not_called()


def test_mesh_contact_overlap_is_rejected_before_solver():
    def overlapping(geometry,**kwargs):
        mesh=mesh_for(geometry['net'])
        if geometry['net']=='A':mesh['terminal_nodes']['a1']=mesh['terminal_nodes']['s1']
        return mesh
    with patch('quick_pi_plugin.board_geometry.extract',side_effect=extract), \
         patch('quick_pi_plugin.mesh.build_mesh',side_effect=overlapping), \
         patch('quick_pi_plugin.solver.solve') as solve,pytest.raises(ValueError,match='electrodes overlap'):
        series_execute(native_board(),Path('Example.kicad_pcb'),request())
    solve.assert_not_called()


@pytest.mark.parametrize('value', [{}, {'schema':1,'branches':[]},
    {'schema':1,'source':'J1.1','sink':'U1.1','branches':[1]},
    {'schema':1,'source':'J1.1','sink':'U1.1','branches':[{'reference':'Q1','model':1}]},
    {'schema':1,'source':'J1.1','sink':'U1.1','branches':[],'source_terminalz':['s2']}])
def test_malformed_saved_path_fails_with_actionable_value_error(value):
    with pytest.raises(ValueError):parse_saved_path(value,inventory())


def test_loaded_endpoint_group_is_retained_until_explicit_peer_choice_changes():
    from quick_pi_plugin.series_editor import SeriesPathDialog
    class Choice:
        def __init__(self,label):self.label=label
        def GetStringSelection(self):return self.label
        def GetSelection(self):return 0
    class Checked:
        def GetValue(self):return True
    controller=object.__new__(SeriesPathDialog)
    controller.inventory=inventory();controller.branches=saved_path()['branches']
    controller.source=Choice('J1.1');controller.sink=Choice('U1.1')
    controller.source_all=Checked();controller.sink_all=Checked()
    controller.endpoint_groups={'source_terminals':['s1'],'sink_terminals':['e1','e2']}
    assert controller._path_data()['source_terminals']==['s1']
    controller.endpoint_groups.clear()
    assert controller._path_data()['source_terminals']==['s1','s2']
