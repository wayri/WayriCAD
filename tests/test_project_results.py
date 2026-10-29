"""Immutable full-result storage, strict intake and historical source custody."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from wayricad_runtime import project_results as library


@pytest.fixture
def project(tmp_path):
    board=tmp_path/'board.kicad_pcb';board.write_bytes(b'(kicad_pcb (version 20240108))\r\n')
    project=board.with_suffix('.kicad_pro');project.write_bytes(b'{"rules":1}')
    digest=hashlib.sha256(board.read_bytes()).hexdigest()
    fingerprints={str(board):digest,str(project):hashlib.sha256(project.read_bytes()).hexdigest(),
                  str(board.with_suffix('.kicad_dru')):None}
    bundle={'schema':'producer-existing/v1','request':{'board_path':str(board),'net':'/Front outputs/SLOT1'},
            'source_sha256':digest,'source_fingerprints':fingerprints,
            'mesh':{'points_mm':[[0,0,.035],[1,0,.035],[0,1,.035]],'triangles':[[0,1,2]]},
            'result':{'potential_V':[3.3,None,3.2],'cell_power_W':[.2]},
            'transient':{'times_s':[0,1,1,2],'source_V':[3.3,None,3.2,3.1]}}
    evidence=dict(board_path=board,source_sha256=digest,tool='Quick PI',version='1.2.3',source_state='saved',
                  units={'potential_V':'V'},coordinate_frame='KiCad PCB XY in mm',z_basis='front-depth')
    return tmp_path,board,bundle,evidence


def test_full_root_shape_canonical_identity_idempotence_and_no_input_changes(project):
    root,board,bundle,evidence=project;before=deepcopy(bundle);board_bytes=board.read_bytes()
    first=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    second=library.save_result(root,'quick_pi_plugin',dict(reversed(list(bundle.items()))),pocket_kivi=evidence)
    assert first['identity']==second['identity'] and first['created'] and not second['created']
    path=Path(first['path']);raw=path.read_bytes();record=json.loads(raw)
    assert path==root/'.wayricad/results/quick-pi'/(first['identity']+'.json')
    metadata=record[library.KEY]
    assert metadata['schema']==library.SCHEMA and metadata['version']==1
    expected=deepcopy(record);expected[library.KEY].pop('identity')
    canonical=(json.dumps(expected,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode()
    assert first['identity']==hashlib.sha256(canonical).hexdigest()
    assert 'timestamp' not in metadata and 'createdAt' not in metadata
    loaded=library.load_result(root,first['relative_path'],plugin='quick-pi')
    assert loaded['bundle']['mesh']==bundle['mesh'] and loaded['bundle']['result']==bundle['result']
    assert loaded['bundle']['transient']==bundle['transient']
    assert loaded['bundle']['request']['net']=='/Front outputs/SLOT1'
    assert library.KEY not in loaded['bundle']
    assert loaded['receipt']['source_state']=='current' and loaded['receipt']['can_restore']
    assert board.read_bytes()==board_bytes and bundle==before
    assert list(path.parent.iterdir())==[path]


@pytest.mark.parametrize('plugin,bundle',[
    ('si',{'path':{'net_name':'/Front outputs/SLOT1','segments':[{'id':'001','impedance_ohm':None}]},
           'eye':{'time_ui':[0,.5,1],'traces_v':[[0,None,1],[1,.5,0]]}}),
    ('therm',{'thermal_network':{'transient':{'spatial_index':{'x_centers_mm':[1,2],'y_centers_mm':[3],
              'cells':[[0,0],[1,0]],'layers':[{'id':0,'z_mm':.035},{'id':31,'z_mm':1.565}],
              'active_cells_per_layer':2},'frames':[{'time_s':0,'temperatures_c':[20,None,21,22]},
                                                {'time_s':1,'temperatures_c':[25,26,27,None]}]}}}),
])
def test_unbound_full_si_and_thermal_arrays_are_readonly_not_falsely_certified(tmp_path,plugin,bundle):
    before=deepcopy(bundle)
    receipt=library.save_result(tmp_path,plugin,bundle,version='2.3')
    loaded=library.load_result(tmp_path,receipt['path'],plugin=plugin)
    assert loaded['bundle']==bundle==before
    assert loaded['receipt']['source_state']=='unverified' and not loaded['receipt']['can_restore']
    assert loaded['receipt']['source_path'] is None


def test_verified_loaded_payload_can_be_saved_idempotently_with_original_context(project):
    root,_,bundle,evidence=project
    first=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    loaded=library.load_result(root,first['path'])
    second=library.save_result(root,'pi',loaded['bundle'],pocket_kivi=evidence)
    assert second['identity']==first['identity'] and not second['created']


def test_stale_board_remains_inspectable_but_cannot_restore_or_be_silently_resaved(project):
    root,board,bundle,evidence=project
    receipt=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    board.write_bytes(b'new revision')
    loaded=library.load_result(root,receipt['path'])
    assert loaded['bundle']['result']==bundle['result']
    assert loaded['receipt']['source_state']=='stale' and not loaded['receipt']['can_restore']
    assert 'bytes changed' in loaded['receipt']['source_issues'][0]
    with pytest.raises(ValueError,match='changed'):
        library.save_result(root,'pi',bundle,pocket_kivi=evidence)


def test_project_rules_and_recorded_absence_are_verified_on_every_load(project):
    root,board,bundle,evidence=project
    receipt=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    board.with_suffix('.kicad_dru').write_bytes(b'(version 1)')
    loaded=library.load_result(root,receipt['path'])
    assert loaded['receipt']['source_state']=='stale'
    assert any('previously absent' in issue for issue in loaded['receipt']['source_issues'])
    board.with_suffix('.kicad_pro').write_bytes(b'{"rules":2}')
    assert any('.kicad_pro: source bytes changed' in issue for issue in library.load_result(root,receipt['path'])['receipt']['source_issues'])


def test_missing_original_source_does_not_destroy_historical_data(project):
    root,board,bundle,evidence=project
    receipt=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    board.unlink()
    loaded=library.load_result(root,receipt['path'])
    assert loaded['receipt']['source_state']=='stale' and loaded['bundle']['result']==bundle['result']


def test_existing_record_mutation_is_never_overwritten(project):
    root,_,bundle,evidence=project
    receipt=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    path=Path(receipt['path']);path.write_bytes(b'{"corrupt":1}')
    with pytest.raises(ValueError,match='collides'):
        library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    assert path.read_bytes()==b'{"corrupt":1}'
    with pytest.raises(ValueError,match='metadata'):
        library.load_result(root,path)


def test_changed_payload_or_plugin_metadata_fails_content_validation(project):
    root,_,bundle,evidence=project
    receipt=library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    path=Path(receipt['path']);record=json.loads(path.read_bytes())
    record['result']['potential_V'][0]=99
    path.write_bytes(library._canonical(record))
    with pytest.raises(ValueError,match='content hash'):
        library.load_result(root,path)
    with pytest.raises(ValueError,match='another plugin'):
        library.load_result(root,path,plugin='si')


@pytest.mark.parametrize('payload',[b'{"a":1,"a":2}',b'{"v":NaN}',b'{"v":Infinity}',b'{"v":1e999}',b'[]',b'\xff'])
def test_strict_duplicate_nan_overflow_and_utf8_rejection(tmp_path,payload):
    folder=tmp_path/'.wayricad/results/quick-pi';folder.mkdir(parents=True)
    path=folder/('a'*64+'.json');path.write_bytes(payload)
    with pytest.raises(ValueError):library.load_result(tmp_path,path)


def test_depth_and_size_limits_apply_to_save_and_load(tmp_path):
    deep={};target=deep
    for _ in range(66):target['next']={};target=target['next']
    with pytest.raises(ValueError,match='nesting'):library.save_result(tmp_path,'pi',deep)
    for bad in (float('nan'),float('inf'),object(),{1:'no key coercion'}):
        with pytest.raises(ValueError):library.save_result(tmp_path,'pi',{'bad':bad})
    with patch.object(library,'MAX_BYTES',128),pytest.raises(ValueError,match='64 MiB'):
        library.save_result(tmp_path,'pi',{'values':['x'*129]})
    folder=tmp_path/'.wayricad/results/quick-pi';folder.mkdir(parents=True,exist_ok=True)
    path=folder/('a'*64+'.json');path.write_bytes(b' '*129)
    with patch.object(library,'MAX_BYTES',128),pytest.raises(ValueError,match='64 MiB'):
        library.load_result(tmp_path,path)


@pytest.mark.parametrize('path',['../outside.json','/outside.json','.wayricad/results/pi/'+('a'*64)+'.json',
    '.wayricad/results/quick-pi/../quick-pi/'+('a'*64)+'.json','.wayricad/results/quick-pi/not-a-hash.json'])
def test_traversal_external_and_noncanonical_record_paths_are_rejected(tmp_path,path):
    with pytest.raises(ValueError):library.load_result(tmp_path,path)
    with pytest.raises(ValueError):library.save_result(tmp_path,'../escape',{})


def test_symbolic_library_directory_cannot_escape_project(tmp_path):
    outside=tmp_path/'outside';outside.mkdir()
    root=tmp_path/'project';root.mkdir()
    try:(root/'.wayricad').symlink_to(outside,target_is_directory=True)
    except OSError:pytest.skip('Test filesystem does not allow symbolic links.')
    with pytest.raises(ValueError,match='symbolic'):library.save_result(root,'pi',{'data':[1]})
    assert list(outside.iterdir())==[]


def test_reparse_directory_is_rejected_before_any_record_write(tmp_path):
    original=library._linked
    with patch.object(library,'_linked',side_effect=lambda path: path==tmp_path/'.wayricad' or original(path)):
        with pytest.raises(ValueError,match='symbolic'):
            library.save_result(tmp_path,'pi',{'data':[1]})
    assert not (tmp_path/'.wayricad').exists()


def test_explicit_portability_cannot_override_snapshot_evidence(project):
    root,_,bundle,evidence=project
    bundle['source_state']='snapshot'
    with pytest.raises(ValueError,match='snapshot'):
        library.save_result(root,'pi',bundle,pocket_kivi=evidence)


def test_atomic_publication_failure_leaves_no_partial_record(project):
    root,_,bundle,evidence=project
    operation='rename' if os.name=='nt' else 'link'
    with patch.object(library.os,operation,side_effect=OSError('injected publication failure')),pytest.raises(OSError,match='publication failure'):
        library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    assert list((root/'.wayricad/results/quick-pi').iterdir())==[]


def test_source_change_during_publication_removes_only_new_record(project):
    root,board,bundle,evidence=project
    operation='rename' if os.name=='nt' else 'link';publish=getattr(library.os,operation)
    def changed(*args,**kwargs):
        result=publish(*args,**kwargs);board.write_bytes(b'changed during publication');return result
    with patch.object(library.os,operation,side_effect=changed),pytest.raises(ValueError,match='changed'):
        library.save_result(root,'pi',bundle,pocket_kivi=evidence)
    assert list((root/'.wayricad/results/quick-pi').iterdir())==[]


def test_listing_is_deterministic_and_checks_each_record(tmp_path):
    records=[library.save_result(tmp_path,plugin,{'value':value},version='1') for plugin,value in [('si',2),('pi',3),('pi',1)]]
    expected=sorted((row['plugin'],row['identity']) for row in records)
    assert [(row['plugin'],row['identity']) for row in library.list_results(tmp_path)]==expected
    assert len(library.list_results(tmp_path,plugin='pi'))==2
    assert library.list_results(tmp_path,plugin='therm')==[]
    with patch.object(library,'MAX_RECORDS',1),pytest.raises(ValueError,match='1,000'):
        library.list_results(tmp_path)


def test_all_actual_saved_examples_keep_viewer_shapes(project):
    root,_,_,_=project
    examples=Path(__file__).resolve().parents[1]/'docs/examples/pocket-kivi'
    for plugin,name in [('pi','quick-pi'),('si','quick-si'),('therm','quick-therm-transient')]:
        bundle=json.loads((examples/(name+'.pocket-kivi.json')).read_bytes())
        receipt=library.save_result(root,plugin,bundle,version='3.6.42')
        loaded=library.load_result(root,receipt['path'])
        assert loaded['bundle']==bundle
        assert loaded['receipt']['source_state']=='unverified'
        if plugin=='pi':assert 'mesh' in loaded['bundle'] and 'result' in loaded['bundle']
        if plugin=='si':assert loaded['bundle']['eye']['traces_v']==bundle['eye']['traces_v']
        if plugin=='therm':assert loaded['bundle']['thermal_network']['transient']['frames']==bundle['thermal_network']['transient']['frames']


def test_unverified_paths_are_portable_without_certifying_or_changing_names(tmp_path):
    root=tmp_path/'project';root.mkdir()
    bundle={'request':{'board_path':str(root/'boards'/'main.kicad_pcb'),
                        'model_path':'C:\\Private User\\models\\driver.ibs','net':'/Front outputs/SLOT1'},
            'source_path':str(root/'boards'/'main.kicad_pcb'),'source_sha256':'a'*64,
            'source_fingerprints':{str(root/'boards'/'main.kicad_pro'):None,
                                   'C:\\Private User\\models\\driver.ibs':'b'*64},
            'nets':{'/Front outputs/SLOT1':{'name':'/Front outputs/SLOT1','id':'/exact/object/id'}},
            'eye':{'time_ui':[0,1,1,2],'traces_v':[[0,None,1,0]]}}
    before=deepcopy(bundle)
    with patch.object(library,'_hash_file',side_effect=AssertionError('No source hashes may be computed')):
        receipt=library.save_result(root,'si',bundle,version='1')
        loaded=library.load_result(root,receipt['path'])
    portable=loaded['bundle']
    assert receipt['source_state']=='unverified' and not receipt['can_restore']
    assert receipt['source_path'] is None
    assert portable['source_path']=='boards/main.kicad_pcb'
    assert portable['request']['model_path'].startswith('_external/')
    assert portable['source_sha256']=='a'*64
    assert 'boards/main.kicad_pro' in portable['source_fingerprints']
    assert list(portable['source_fingerprints'].values()).count(None)==1
    assert portable['nets']==bundle['nets'] and portable['eye']==bundle['eye']
    assert b'Private User' not in Path(receipt['path']).read_bytes()
    assert bundle==before


def test_unverified_relative_and_absolute_paths_have_same_content_identity(tmp_path):
    first=library.save_result(tmp_path,'pi',{'request':{'board_path':str(tmp_path/'board.kicad_pcb')},'values':[1,None]})
    second=library.save_result(tmp_path,'pi',{'request':{'board_path':'board.kicad_pcb'},'values':[1,None]})
    assert first['identity']==second['identity'] and not second['created']
