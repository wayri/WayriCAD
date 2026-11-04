"""Independent series cases preserve complete reviewed paths and file identity."""
from copy import deepcopy
import hashlib
import json

import pytest

from quick_pi_plugin.batch import SCHEMA,execute,initial_study,load_study,parse_study,validate_study
from quick_pi_plugin.series_editor import parse_saved_path
from quick_pi_plugin.study_setup_file import capture,restore,validate


def inventory():
    rows=[]
    for ref,pads in [('J1',[('s1','A'),('s2','A')]),
            ('Q1',[('a1','A'),('a2','A'),('b1','B'),('b2','B'),('gate','G')]),
            ('Q2',[('p1','A'),('p2','A'),('q1','B'),('q2','B')]),
            ('D1',[('d1','B'),('d2','C')]),('U1',[('e1','C'),('e2','C')])]:
        for number,(identifier,net) in enumerate(pads,1):
            rows.append(dict(id=identifier,label=ref+'.'+str(number),reference=ref,
                footprint_uuid=ref,net=net))
    return {'nets':['A','B','C','G'],'terminals':rows}


def case(name='First setup',voltage=3.3,current=2.,resistance='100mΩ',drop='0.6V'):
    path={'schema':1,'source':'J1.1','sink':'U1.1','source_terminals':['s1','s2'],
        'sink_terminals':['e1','e2'],'branches':[
            {'reference':'Q1','from_pad':'a1','to_pad':'b1','from_pads':['a1','a2'],
             'to_pads':['b1','b2'],'model':resistance,'parallel':[
                {'footprint_uuid':'Q2','from_pad':'p1','to_pad':'q1',
                 'from_pads':['p1','p2'],'to_pads':['q1','q2'],'model':'200mΩ'}]},
            {'reference':'D1','from_pad':'d1','to_pad':'d2','model':drop}]}
    request=parse_saved_path(path,inventory())
    request.pop('action')
    request.update(source_voltage=voltage,sink_current=current)
    return {'name':name,'electrical':request}


def study(*cases):
    return {'schema':SCHEMA,'cases':list(cases) or [case()]}


def board(tmp_path):
    path=tmp_path/'Example.kicad_pcb';path.write_text('(kicad_pcb)',encoding='utf-8')
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def test_execute_preserves_independent_full_series_models_and_every_group(tmp_path):
    path,sha=board(tmp_path)
    configured=study(case(),case('Second setup',5.,.75,'25mΩ','diode(Vf=0.7V,Iref=1A,n=2,T=25C)'))
    before=deepcopy(configured);received=[]
    def runner(request):
        received.append(deepcopy(request))
        return {'request':deepcopy(request),'result':{'source_voltage_V':request['source_voltage'],
            'sink_current_A':request['sink_current']},'source_sha256':sha}
    result=execute(dict(board_path=str(path),source_sha256=sha,study=configured),runner)
    assert result['batch']['status']=='COMPLETED'
    assert len(received)==2
    for request,configured_case,row in zip(received,configured['cases'],result['batch']['cases']):
        assert request==dict(configured_case['electrical'],action='solve',board_path=str(path.resolve()))
        assert row['electrical']['request']==request
        assert request['source_terminals']==['s1','s2']
        assert request['sink_terminals']==['e1','e2']
        assert request['series'][0]['parallel'][0]['from_pads']==['p1','p2']
        assert request['series'][0]['parallel'][0]['to_pads']==['q1','q2']
        assert len(request['series'])==2
    assert received[0]['series'][0]['resistance_ohm']==.1
    assert received[1]['series'][0]['resistance_ohm']==.025
    assert received[0]['series'][1]['fixed_drop_v']==.6
    assert received[1]['series'][1]['diode']['vf_ref_v']==.7
    assert configured==before
    assert hashlib.sha256(path.read_bytes()).hexdigest()==sha


def test_series_seed_and_json_file_roundtrip_preserve_all_case_settings(tmp_path):
    electrical=case()['electrical']
    seeded=initial_study(dict(electrical,action='solve',board_path='private'))
    assert seeded['cases'][0]['electrical']==electrical
    configured=study(case(),case('Other setup',12.,3.,'10mΩ','1V'))
    path=tmp_path/'setups.json';path.write_text(json.dumps(configured),encoding='utf-8')
    loaded,sha=load_study(path)
    assert loaded==configured
    assert parse_study(path.read_bytes())==configured
    assert sha==hashlib.sha256(path.read_bytes()).hexdigest()


def test_series_batch_rejects_stale_board_or_study_for_every_case(tmp_path):
    path,sha=board(tmp_path);configured=study(case())
    with pytest.raises(ValueError,match='changed'):
        execute(dict(board_path=str(path),source_sha256='old',study=configured),lambda request:None)
    for changed in ('board','study'):
        source=tmp_path/'setups.json';source.write_text(json.dumps(configured),encoding='utf-8')
        study_sha=hashlib.sha256(source.read_bytes()).hexdigest()
        def runner(request):
            (path if changed=='board' else source).write_text('changed',encoding='utf-8')
            return {'result':{},'source_sha256':sha}
        with pytest.raises(ValueError,match='every case'):
            execute(dict(board_path=str(path),study=configured,study_input_path=str(source),
                study_file_sha256=study_sha),runner)
        path.write_text('(kicad_pcb)',encoding='utf-8')


@pytest.mark.parametrize('edit',[
    lambda value:value['cases'][0]['electrical'].update(series=[]),
    lambda value:value['cases'][0]['electrical'].update(series=[None]),
    lambda value:value['cases'][0]['electrical'].update(sink_current=None),
    lambda value:value['cases'][0]['electrical'].update(source_terminals=[]),
    lambda value:value['cases'][0]['electrical'].update(sink_terminals=['e1','e1']),
    lambda value:value['cases'][0]['electrical']['series'][0].update(from_pads=['a1','s2']),
    lambda value:value['cases'][0]['electrical']['series'][0].update(resistance_ohm=-1),
    lambda value:value['cases'][0]['electrical']['series'][0]['parallel'][0].update(inductance_h=float('inf')),
    lambda value:value['cases'][0]['electrical']['series'][0]['parallel'][0].update(fixed_drop_v=.5),
    lambda value:value['cases'][0]['electrical']['series'][1].update(diode={}),
])
def test_malformed_series_rejected_before_any_case_runs(tmp_path,edit):
    path,_=board(tmp_path);configured=study(case());edit(configured);calls=[]
    with pytest.raises(ValueError):execute(dict(board_path=str(path),study=configured),calls.append)
    assert calls==[]


@pytest.mark.parametrize('electrical,extra,shared',[
    ({'load_power_W':1.},{},False),({'load_resistance_ohm':10.},{},False),
    ({'model_dimension':'3d'},{},False),({'package_conduction':{}},{},False),
    ({},{'return_conduction':{}},False),({},{'electrothermal':{}},False),
    ({},{},True),({'sinks':[{'terminal':'e1','current_A':1.}]},{},False),
])
def test_unsupported_series_combinations_rejected(electrical,extra,shared):
    configured=study(case());configured['cases'][0]['electrical'].update(electrical)
    configured['cases'][0].update(extra)
    if shared:configured['shared_returns']=[{}]
    with pytest.raises(ValueError,match='independent 2.5D prescribed-current'):
        validate_study(configured)


def dialog(configured):
    class Text:
        def __init__(self,value):self.value=value
        def GetValue(self):return self.value
        def ChangeValue(self,value):self.value=value
    cls=type('BatchStudyDialog',(),{})
    result=cls();result.inventory=inventory();result.setup=Text(json.dumps(configured))
    result.changed=lambda:setattr(result,'invalidated',True);result.Layout=lambda:None
    return result


def test_saved_batch_setup_roundtrips_series_on_multiple_nets():
    configured=study(case(),case('Different settings',8.,4.,'30mΩ','0.8V'))
    editor=dialog(configured);state=capture(editor)
    saved=json.loads(json.dumps(state));assert validate(editor,saved)==state
    editor.setup.ChangeValue('{}');restore(editor,saved)
    assert capture(editor)==state and editor.invalidated


def test_saved_batch_setup_resolves_anchor_labels_with_uuid_groups():
    configured=study(case());electrical=configured['cases'][0]['electrical']
    electrical.update(source_terminal='J1.1',sink_terminal='U1.1')
    electrical['series'][0].update(from_pad='Q1.1',to_pad='Q1.3')
    editor=dialog(configured)
    assert validate(editor,capture(editor))==capture(editor)


@pytest.mark.parametrize('edit',[
    lambda value:value['cases'][0]['electrical']['series'][0].update(from_pads=['a2']),
    lambda value:value['cases'][0]['electrical']['series'][0].update(from_pads=['a1','gate']),
    lambda value:value['cases'][0]['electrical']['series'][0].update(from_pads=['a1','Q1.1']),
    lambda value:value['cases'][0]['electrical']['series'][1].update(to_pad='missing'),
    lambda value:value['cases'][0]['electrical'].update(net='B'),
])
def test_saved_batch_setup_revalidates_exact_pad_topology(edit):
    configured=study(case());edit(configured);editor=dialog(configured)
    with pytest.raises(ValueError):validate(editor,capture(editor))


def test_nonseries_saved_batch_still_requires_every_pad_on_the_selected_net():
    configured=study({'name':'Single net','electrical':dict(net='A',source_terminal='s1',
        source_voltage=3.3,sink_terminal='e1',sink_current=1.)})
    editor=dialog(configured)
    with pytest.raises(ValueError,match='no longer belongs to its rail'):validate(editor,capture(editor))
