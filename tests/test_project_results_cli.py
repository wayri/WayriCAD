"""Common project-result CLI performs strict data operations, never solves/auths."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wayricad_runtime import project_results as library
from wayricad_runtime.project_results_cli import main


def invoke(root,arguments,capsys):
    status=main(['--project',str(root),*map(str,arguments)])
    captured=capsys.readouterr()
    return status,json.loads(captured.out) if captured.out else None,captured.err


@pytest.mark.parametrize('plugin',['quick-pi','quick-si','quick-therm','quick-emerge'])
def test_common_save_list_show_complete_payload_and_explicit_unverified(tmp_path,capsys,plugin):
    bundle={'mesh':{'points_mm':[[0,0],[1,0],[0,1]],'triangles':[[0,1,2]]},
            'result':{'potential_V':[1,None,0]},'eye':{'time_ui':[0,1,1],'traces_v':[[None,1,0]]}}
    source=tmp_path/'input.json';source.write_text(json.dumps(bundle))
    status,receipt,error=invoke(tmp_path,['save',source,'--plugin',plugin,'--version','1.2'],capsys)
    assert status==0 and not error and receipt['source_state']=='unverified'
    status,rows,_=invoke(tmp_path,['list','--plugin',plugin],capsys)
    assert status==0 and len(rows)==1 and rows[0]['identity']==receipt['identity']
    status,summary,_=invoke(tmp_path,['show',receipt['relative_path'],'--plugin',plugin],capsys)
    assert status==0 and 'bundle' not in summary and summary['source_state']=='unverified'
    status,loaded,_=invoke(tmp_path,['show',receipt['relative_path'],'--plugin',plugin,'--full'],capsys)
    assert status==0 and loaded['bundle']==bundle and loaded['receipt']['source_state']=='unverified'
    assert source.read_text()==json.dumps(bundle)


def test_verified_save_requires_original_explicit_evidence_and_reports_stale_later(tmp_path,capsys):
    board=tmp_path/'board.kicad_pcb';board.write_bytes(b'original saved board')
    digest=hashlib.sha256(board.read_bytes()).hexdigest()
    source=tmp_path/'input.json';source.write_text(json.dumps({'source_sha256':digest,'source_path':'board.kicad_pcb','result':{'values':[1,None]}}))
    evidence=tmp_path/'evidence.json';evidence.write_text(json.dumps(dict(board_path='board.kicad_pcb',
        source_sha256=digest,source_state='saved',tool='Quick PI',version='1.2')))
    status,receipt,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--evidence',evidence],capsys)
    assert status==0 and not error and receipt['source_state']=='current'
    board.write_bytes(b'new saved board')
    status,loaded,_=invoke(tmp_path,['show',receipt['relative_path'],'--full'],capsys)
    assert status==0 and loaded['receipt']['source_state']=='stale' and not loaded['receipt']['can_restore']
    status,output,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--evidence',evidence],capsys)
    assert status==2 and output is None and 'changed' in error
    assert len(list((tmp_path/'.wayricad/results/quick-pi').glob('*.json')))==1


def test_default_save_does_not_infer_a_certificate_from_hash_shaped_metadata(tmp_path,capsys):
    source=tmp_path/'input.json';source.write_text(json.dumps({'source_path':'missing.kicad_pcb','source_sha256':'a'*64}))
    status,receipt,_=invoke(tmp_path,['save',source,'--plugin','quick-si'],capsys)
    assert status==0 and receipt['source_state']=='unverified' and receipt['source_path'] is None


@pytest.mark.parametrize('content',['{"x":1,"x":2}','{"x":NaN}','{"x":1e999}','[]','{bad'])
def test_input_intake_rejects_bad_json_without_output_or_library(tmp_path,capsys,content):
    source=tmp_path/'input.json';source.write_text(content)
    status,output,error=invoke(tmp_path,['save',source,'--plugin','quick-pi'],capsys)
    assert status==2 and output is None and json.loads(error)['status']=='error'
    assert not (tmp_path/'.wayricad').exists()


def test_cli_uses_library_byte_and_depth_limits(tmp_path,capsys):
    source=tmp_path/'large.json';source.write_bytes(b'x'*129)
    with patch.object(library,'MAX_BYTES',128):
        status,output,error=invoke(tmp_path,['save',source,'--plugin','quick-pi'],capsys)
    assert status==2 and output is None and '64 MiB' in error
    source.write_text('{"next":'*66+'{}'+'}'*66)
    status,output,error=invoke(tmp_path,['save',source,'--plugin','quick-pi'],capsys)
    assert status==2 and output is None and 'nesting' in error


@pytest.mark.parametrize('evidence',[
    {'board_path':'board.kicad_pcb','source_sha256':'a'*64,'tool':'Quick PI','version':'1','source_state':'live'},
    {'board_path':'board.kicad_pcb','tool':'Quick PI','version':'1','source_state':'saved'},
    {'board_path':'board.kicad_pcb','source_sha256':'a'*64,'tool':'Quick PI','version':'1','source_state':'saved','token':'not-accepted'},
])
def test_invalid_evidence_never_falls_back_to_unverified_or_echoes_values(tmp_path,capsys,evidence):
    source=tmp_path/'input.json';source.write_text('{"result":{"value":1}}')
    binding=tmp_path/'binding.json';binding.write_text(json.dumps(evidence))
    status,output,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--evidence',binding],capsys)
    assert status==2 and output is None and 'not-accepted' not in error
    assert not (tmp_path/'.wayricad').exists()


def test_show_missing_file_and_plugin_mismatch_is_explicit(tmp_path,capsys):
    status,output,error=invoke(tmp_path,['show','../outside.json'],capsys)
    assert status==2 and output is None
    receipt=library.save_result(tmp_path,'pi',{'values':[1]})
    status,output,error=invoke(tmp_path,['show',receipt['relative_path'],'--plugin','quick-si'],capsys)
    assert status==2 and output is None and 'another plugin' in error


def test_named_output_relative_external_paths_and_full_arrays(tmp_path,capsys):
    project=tmp_path/'project';project.mkdir()
    external=tmp_path/'shared';external.mkdir()
    bundle={'frequencies_hz':[1e9,2e9], 's_parameters':{'S11':[[.1,.2],[.3,.4]]},
            'field':{'x_mm':[0,1],'y_mm':[0,1],'norm_e_v_m':[[1,None],[2,3]]}}
    source=project/'producer.json';source.write_text(json.dumps(bundle))
    for destination in (Path('named study'),external/'shared data.json'):
        status,receipt,error=invoke(project,['save',source,'--plugin','quick-emerge','--output',destination],capsys)
        assert status==0 and not error
        chosen=Path(receipt['path'])
        assert chosen.is_file() and chosen.suffix=='.json'
        record=chosen.relative_to(project) if chosen.is_relative_to(project) else chosen
        status,loaded,error=invoke(project,['show',record,'--plugin','quick-emerge','--full'],capsys)
        assert status==0 and not error and loaded['bundle']==bundle
        assert loaded['receipt']['source_state']=='unverified'
    assert not (project/'.wayricad').exists()


def test_named_output_overwrite_needs_explicit_flag_and_never_replaces_input(tmp_path,capsys):
    source=tmp_path/'input.json';source.write_text('{"values":[1,null,3]}')
    before=source.read_bytes();output=tmp_path/'named.json';output.write_bytes(b'keep')
    status,_,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--output','named'],capsys)
    assert status==2 and '--overwrite' in error and output.read_bytes()==b'keep'
    status,_,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--output',output,'--overwrite'],capsys)
    assert status==0 and not error and library.KEY in output.read_text()
    status,_,error=invoke(tmp_path,['save',source,'--plugin','quick-pi','--output',source,'--overwrite'],capsys)
    assert status==2 and 'overwrite' in error and source.read_bytes()==before
