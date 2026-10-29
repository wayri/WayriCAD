"""Opt-in portable sidecars retain original report evidence and atomic custody."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wayricad_runtime import report_ui
from wayricad_runtime.pocket_report import evidence_context, producer_version


@pytest.fixture
def source(tmp_path):
    board=tmp_path/'board.kicad_pcb'
    board.write_bytes(b'(kicad_pcb (version 20240108))\r\n')
    digest=hashlib.sha256(board.read_bytes()).hexdigest()
    return board,digest


def evidence(source):
    board,digest=source
    return dict(board_path=board,source_sha256=digest,tool='Test producer',version='1.2.3',source_state='saved')


def bound(source):
    board,digest=source
    return {'request':{'board_path':str(board)},'source_sha256':digest,
            'mesh':{'points_mm':[[0,0],[1,0],[0,1]],'triangles':[[0,1,2]]},
            'result':{'potential_V':[1,None,0]},'net':'/Front outputs/SLOT1'}


def pi(source):
    from quick_pi_plugin.tests.test_report import bundle
    value=bundle()
    board,digest=source
    value['geometry'].update(source_path=str(board),source_sha256=digest,
        z_convention='Copper midplanes; positive Z down from the top copper surface.')
    value['request']['board_path']=str(board)
    value['result']['potential_V'][1]=None
    return value


def test_default_common_pair_retains_exact_bytes_and_return_contract(tmp_path):
    bundle={'values':[1,None,2],'schema':'existing/v1'}
    path=tmp_path/'report.html'
    result=report_ui.publish_report(path,'plain original document',bundle)
    assert result=={'html':str(path),'json':str(path.with_suffix('.json'))}
    assert path.read_bytes()==b'plain original document'
    assert path.with_suffix('.json').read_bytes()==(json.dumps(bundle,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    assert {p.name for p in tmp_path.iterdir()}=={'report.html','report.json'}


def test_triple_keeps_original_evidence_and_root_shape_and_adds_visible_link(source,tmp_path):
    bundle=bound(source);before=deepcopy(bundle)
    path=tmp_path/'result.html'
    result=report_ui.publish_report(path,'<html><h1>Results</h1></html>',bundle,pocket_kivi=evidence(source))
    sidecar=Path(result['pocket_kivi_json'])
    assert sidecar.name=='result.pocket-kivi.json'
    assert json.loads(path.with_suffix('.json').read_bytes())==bundle
    portable=json.loads(sidecar.read_bytes())
    assert portable['mesh']==bundle['mesh'] and portable['result']==bundle['result']
    assert portable['net']=='/Front outputs/SLOT1' and portable['source_path']=='board.kicad_pcb'
    assert 'Pocket KiView' in path.read_text() and sidecar.name in path.read_text()
    assert bundle==before and source[0].read_bytes().endswith(b'\r\n')


def test_portable_link_is_visible_without_h1(source,tmp_path):
    path=tmp_path/'no-heading.html'
    report_ui.publish_report(path,'Report content',bound(source),pocket_kivi=evidence(source))
    assert 'no-heading.pocket-kivi.json' in path.read_text()


def test_three_existing_outputs_roll_back_if_third_replace_fails(source,tmp_path):
    path=tmp_path/'result.html'
    targets=[path.with_suffix('.json'),tmp_path/'result.pocket-kivi.json',path]
    for index,target in enumerate(targets):target.write_bytes(('original '+str(index)).encode())
    original={target:target.read_bytes() for target in targets}
    replace=report_ui.os.replace;failed=False
    def fail_html_once(staging,target):
        nonlocal failed
        if Path(target)==path and not failed:
            failed=True
            raise OSError('third replacement failed')
        return replace(staging,target)
    with patch.object(report_ui.os,'replace',side_effect=fail_html_once),pytest.raises(OSError,match='third replacement'):
        report_ui.publish_report(path,'<h1>Candidate</h1>',bound(source),pocket_kivi=evidence(source))
    assert all(target.read_bytes()==value for target,value in original.items())
    assert {p.name for p in tmp_path.iterdir()}=={source[0].name,*[target.name for target in targets]}


def test_source_change_during_publication_rolls_back_all_three(source,tmp_path):
    path=tmp_path/'result.html';sidecar=tmp_path/'result.pocket-kivi.json'
    targets=[path,path.with_suffix('.json'),sidecar]
    for target in targets:target.write_bytes(b'original')
    replace=report_ui.os.replace;changed=False
    def mutate(staging,target):
        nonlocal changed
        result=replace(staging,target)
        if Path(target)==sidecar and not changed:
            changed=True
            source[0].write_bytes(b'changed source')
        return result
    with patch.object(report_ui.os,'replace',side_effect=mutate),pytest.raises(ValueError,match='changed'):
        report_ui.publish_report(path,'candidate',bound(source),pocket_kivi=evidence(source))
    assert all(target.read_bytes()==b'original' for target in targets)


def test_stale_or_protected_source_never_replaces_outputs(source,tmp_path):
    path=tmp_path/'result.html';path.write_bytes(b'original html')
    bundle=bound(source)
    source[0].write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):
        report_ui.publish_report(path,'candidate',bundle,pocket_kivi=evidence(source))
    assert path.read_bytes()==b'original html' and not path.with_suffix('.json').exists()
    source[0].write_bytes(b'(kicad_pcb (version 20240108))\r\n')
    sidecar=tmp_path/'result.pocket-kivi.json';sidecar.write_bytes(b'input study')
    bundle['request']['study_input_path']=str(sidecar)
    with pytest.raises(ValueError,match='overwrite'):
        report_ui.publish_report(path,'candidate',bundle,pocket_kivi=evidence(source))
    assert path.read_bytes()==b'original html' and sidecar.read_bytes()==b'input study'


@pytest.mark.parametrize('location',['root','request','geometry','mesh_geometry','fingerprints'])
def test_context_derives_original_digest_without_hashing(source,location):
    board,digest=source
    if location=='root':bundle={'board_path':str(board),'source_sha256':digest}
    elif location=='request':bundle={'request':{'board_path':str(board),'source_sha256':digest}}
    elif location=='geometry':bundle={'geometry':{'source_path':str(board),'source_sha256':digest}}
    elif location=='mesh_geometry':bundle={'mesh':{'geometry':{'source_path':str(board),'source_sha256':digest}}}
    else:bundle={'source_fingerprints':{str(board):digest}}
    with patch('pathlib.Path.read_bytes',side_effect=AssertionError('must not compute a fresh digest')):
        context=evidence_context(bundle,tool='Test',version='1',board_path=board)
    assert context['source_sha256']==digest and context['source_state']=='saved'


@pytest.mark.parametrize('bundle',[{}, {'source_hash':'a'*64}, {'study_sha256':'a'*64},
    {'model_sha256':'a'*64}, {'source_fingerprints':{}}])
def test_unbound_or_model_hash_cannot_become_pcb_evidence(source,bundle):
    with pytest.raises(ValueError,match='fingerprint'):
        evidence_context(bundle,tool='Test',version='1',board_path=source[0])


@pytest.mark.parametrize('marker',[{'source_state':'live'},{'request':{'source_state':'unsaved'}},
    {'geometry_origin':'saved snapshot'},{'board_binding':'unbound'},{'report':{'is_snapshot':True}}])
def test_live_unsaved_snapshot_flags_cannot_be_overridden(source,marker):
    bundle=bound(source)
    for key,value in marker.items():
        if key=='request':bundle['request'].update(value)
        else:bundle[key]=value
    with pytest.raises(ValueError,match='saved PCB binding'):
        evidence_context(bundle,tool='Test',version='1')


def test_context_rejects_conflicting_paths_and_original_fingerprints(source,tmp_path):
    bundle=bound(source);bundle['geometry']={'source_path':str(tmp_path/'other.kicad_pcb')}
    with pytest.raises(ValueError,match='paths conflict'):
        evidence_context(bundle,tool='Test',version='1')
    bundle=bound(source);bundle['geometry']={'source_sha256':'0'*64}
    with pytest.raises(ValueError,match='fingerprints conflict'):
        evidence_context(bundle,tool='Test',version='1')


def test_versions_use_actual_package_or_adjacent_source_and_pcm_metadata(tmp_path):
    package=SimpleNamespace(__version__='7.8.9')
    assert producer_version(package=package)=='7.8.9'
    assert producer_version(version='1.2.3')=='1.2.3'
    plugin=tmp_path/'source-plugin';plugin.mkdir()
    metadata=plugin/'metadata.json';metadata.write_text(json.dumps({'versions':[{'version':'2.3.4'}]}))
    assert producer_version(module_file=plugin/'report.py')=='2.3.4'
    pcm=tmp_path/'pcm';(pcm/'plugins').mkdir(parents=True)
    (pcm/'metadata.json').write_text(json.dumps({'versions':[{'version':'4.5.6'}]}))
    assert producer_version(module_file=pcm/'plugins'/'report.py')=='4.5.6'
    assert producer_version(module_file=tmp_path/'unbound.py') is None
    with pytest.raises(ValueError,match='version is unavailable'):
        evidence_context(bound((tmp_path/'board.kicad_pcb','a'*64)),tool='Test')


def test_pi_writer_keeps_original_json_and_complete_sidecar(source,tmp_path):
    from quick_pi_plugin import report
    bundle=pi(source);before=deepcopy(bundle);path=tmp_path/'pi.html'
    with patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'):
        ordinary=report.write_report(path,bundle)
        original=Path(ordinary['json']).read_bytes()
        result=report.write_report(path,bundle,pocket_kivi=True)
    assert Path(result['json']).read_bytes()==original
    portable=json.loads(Path(result['pocket_kivi_json']).read_bytes())
    assert portable['mesh']['points_mm']==bundle['mesh']['points_mm']
    assert portable['result']['potential_V']==bundle['result']['potential_V']
    assert portable['pocket_kivi_export']['zBasis']=='front-depth'
    assert portable['pocket_kivi_export']['tool']=='Quick PI'
    assert bundle==before


def test_linked_child_cannot_be_mislabelled_as_complete_portable_result(source,tmp_path):
    from quick_pi_plugin import report
    path=tmp_path/'child.html'
    with patch.object(report,'_report_snapshot',side_effect=AssertionError('reject before rendering')):
        with pytest.raises(ValueError,match='not complete'):
            report.write_report(path,pi(source),evidence_reference={'json':'parent.json','json_pointer':'/case'},pocket_kivi=True)
    assert not path.exists()
    descriptor={'schema':'wayricad.pi-report-reference/v1','evidence_reference':{'json':'parent.json','json_pointer':'/case'}}
    with pytest.raises(ValueError,match='not complete'):
        report_ui.publish_report(path,'descriptor',descriptor,pocket_kivi=evidence(source))


def test_volume_opt_in_keeps_all_tetrahedra_and_default_serialization(source,tmp_path):
    from quick_pi_plugin.tests.test_volume_view import sample_bundle
    from quick_pi_plugin.volume_view import write_volume_report
    bundle=sample_bundle();board,digest=source
    bundle['geometry'].update(source_path=str(board),source_sha256=digest)
    before=deepcopy(bundle)
    ordinary=write_volume_report(tmp_path/'volume.html',bundle)
    assert Path(ordinary['json']).read_bytes()==json.dumps(bundle,allow_nan=False).encode()
    result=write_volume_report(tmp_path/'portable-volume.html',bundle,pocket_kivi=True)
    portable=json.loads(Path(result['pocket_kivi_json']).read_bytes())
    assert portable['mesh']==bundle['mesh'] and portable['result']==bundle['result']
    assert portable['result']['cell_power_W'][1] is None
    assert portable['pocket_kivi_export']['zBasis'] is None
    assert bundle==before


def test_therm_writer_keeps_temperatures_and_unknowns(source,tmp_path):
    from quick_therm_plugin.tests.test_sankey import bundle as thermal_bundle
    from quick_therm_plugin.report import write_report
    bundle=thermal_bundle();board,digest=source
    bundle.update(source_sha256=digest,request={'board_path':str(board)})
    before=deepcopy(bundle);path=tmp_path/'therm.html'
    ordinary=write_report(path,bundle)
    original=Path(ordinary['json']).read_bytes()
    result=write_report(path,bundle,pocket_kivi=True)
    assert Path(result['json']).read_bytes()==original
    portable=json.loads(Path(result['pocket_kivi_json']).read_bytes())
    assert portable['quick_therm']==bundle['quick_therm']
    assert portable['quick_therm']['board_c'] is None
    assert portable['pocket_kivi_export']['tool']=='QuickTherm'
    assert portable['pocket_kivi_export']['version']==producer_version(package='quick_therm_plugin')
    assert bundle==before


def test_unbound_thermal_and_circuit_models_keep_default_export_available(tmp_path):
    from quick_therm_plugin.tests.test_sankey import bundle as thermal_bundle
    from quick_therm_plugin.report import write_report
    value=thermal_bundle();path=tmp_path/'thermal.html'
    assert 'pocket_kivi_json' not in write_report(path,value)
    with pytest.raises(ValueError,match='saved PCB path'):
        write_report(tmp_path/'unavailable.html',value,pocket_kivi=True)


def test_batch_sidecars_are_full_cases_while_parent_and_descriptors_stay_exact(source,tmp_path):
    from quick_pi_plugin import report
    child=pi(source)
    bundle={'batch':{'status':'COMPLETED','cases':[
        {'name':'Supply','status':'COMPLETED','electrical':child},
        {'name':'Other','status':'COMPLETED','electrical':deepcopy(child)}]}}
    before=deepcopy(bundle);path=tmp_path/'batch.html'
    with patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'):
        original=report.write_batch_report(path,bundle)
        parent_bytes=Path(original['json']).read_bytes()
        descriptors={relative:(tmp_path/relative).with_suffix('.json').read_bytes() for relative in original['case_reports']}
        result=report.write_batch_report(path,bundle,pocket_kivi=True)
    assert Path(result['json']).read_bytes()==parent_bytes
    assert len(result['pocket_kivi_jsons'])==2
    expected_mesh=deepcopy(child['mesh']);expected_mesh['geometry']['source_path']='board.kicad_pcb'
    for portable_path,relative in zip(result['pocket_kivi_jsons'],result['case_reports']):
        portable=json.loads(Path(portable_path).read_bytes())
        assert portable['mesh']==expected_mesh and portable['result']==child['result']
        assert (tmp_path/relative).with_suffix('.json').read_bytes()==descriptors[relative]
        assert 'evidence_reference' not in portable
        assert Path(portable_path).name in (tmp_path/relative).read_text()
    assert 'Pocket KiView' in path.read_text()
    assert bundle==before


def test_batch_shared_return_sidecar_preserves_exact_existing_physical_bundle(source,tmp_path):
    from quick_pi_plugin import report
    from quick_pi_plugin.shared_return import physical_report_bundle
    from quick_pi_plugin.solver import solve
    child=pi(source);mesh=child['mesh']
    sources=[i for i,p in enumerate(mesh['points_mm']) if p[0]==0]
    sinks=[i for i,p in enumerate(mesh['points_mm']) if p[0]==10]
    child['result']=solve(mesh,sources,sinks,source_voltage=0,sink_current=2)
    load={'case':'Supply','sink':'chip','current_A':2.,'ground_rise_V':.01,
          'supply_drop_V':.02,'delivered_load_voltage_V':3.27,'voltage_limits_met':True}
    group={'name':'Common ground','status':'COMPLETED','return_conduction':child,'loads':[load],
           'return_loss_W':.02,'total_loss_W':.06,'power_balance_error_W':0.}
    bundle={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED',
        'shared_return':{'group':'Common ground','loads':[load]}}],'shared_returns':[group]}}
    before=deepcopy(bundle)
    expected=physical_report_bundle(group)
    with patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'):
        result=report.write_batch_report(tmp_path/'return.html',bundle,pocket_kivi=True)
    assert len(result['pocket_kivi_jsons'])==1
    portable=json.loads(Path(result['pocket_kivi_jsons'][0]).read_bytes())
    expected_mesh=deepcopy(expected['mesh']);expected_mesh['geometry']['source_path']='board.kicad_pcb'
    assert portable['mesh']==expected_mesh and portable['result']==expected['result']
    assert portable['physical_return'] is True
    descriptor=json.loads((tmp_path/result['case_reports'][0]).with_suffix('.json').read_bytes())
    assert descriptor['schema']=='wayricad.pi-report-reference/v1'
    assert 'sign_transforms' in descriptor['evidence_reference']
    assert bundle==before


def test_batch_portable_budget_error_is_not_swallowed_or_partially_published(source,tmp_path):
    from quick_pi_plugin import report
    from wayricad_runtime import pocket_kivi_export
    bundle={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED','electrical':pi(source)}]}}
    path=tmp_path/'batch.html';path.write_bytes(b'previous report')
    with patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'),\
         patch.object(pocket_kivi_export,'MAX_BYTES',128),pytest.raises(ValueError,match='64 MiB'):
        report.write_batch_report(path,bundle,pocket_kivi=True)
    assert path.read_bytes()==b'previous report'
    assert not path.with_suffix('.json').exists()
    assert not (tmp_path/'batch-cases').exists()


def test_batch_final_failure_restores_parent_descriptors_and_portable_children(source,tmp_path):
    from quick_pi_plugin import report
    bundle={'batch':{'status':'COMPLETED','cases':[{'name':'Supply','status':'COMPLETED','electrical':pi(source)}]}}
    path=tmp_path/'batch.html'
    with patch.object(report,'_report_snapshot',return_value='<figure>fixture</figure>'):
        report.write_batch_report(path,bundle,pocket_kivi=True)
        originals={item:item.read_bytes() for item in tmp_path.rglob('*') if item.is_file()}
        replace=report_ui.os.replace;failed=False
        def fail_parent_once(staging,target):
            nonlocal failed
            if Path(target)==path and not failed:
                failed=True
                raise OSError('batch parent replacement failed')
            return replace(staging,target)
        with patch.object(report_ui.os,'replace',side_effect=fail_parent_once),pytest.raises(OSError,match='batch parent'):
            report.write_batch_report(path,bundle,pocket_kivi=True)
    assert {item:item.read_bytes() for item in tmp_path.rglob('*') if item.is_file()}==originals
