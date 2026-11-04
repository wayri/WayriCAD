"""Series setup queues preserve models and grouped pads through saved setups."""
from copy import deepcopy
import json

import pytest

from quick_pi_plugin.series_batch_setup import make_case,validate_state,SCHEMA
from quick_pi_plugin.tests.series_inference_fixture import inventory
from quick_pi_plugin.series_inference import reviewed_path
from wayricad_runtime.series_topology import infer_series_paths


def path():
    board=inventory();proposal=infer_series_paths(board,'J1.1','J2.1')
    selections=[[dict(footprint_uuid=p['footprint_uuid'],model=('100m' if p['reference'] in ('Q1','Q3') else '200m'),
                         from_pads=p['from_pads'],to_pads=p['to_pads'])
                 for p in stage['parts']] for stage in proposal['routes'][0]['stages']]
    return reviewed_path(proposal,0,selections,board)


def test_named_series_cases_and_source_bound_setup_roundtrip(tmp_path):
    from wayricad_runtime.project_setup import make_setup,save_setup,load_setup
    a=make_case(path(),inventory(),'3V3 rail','3.3','2')
    b=make_case(path(),inventory(),'5V rail','5','1')
    state=dict(schema=SCHEMA,cases=[a,b],draft=dict(name='Next',voltage='12',current='3'))
    expected=validate_state(state,inventory())
    source=tmp_path/'example.kicad_pcb';source.write_bytes(b'source revision')
    target=tmp_path/'series-batch.setup.json'
    save_setup(target,make_setup('quick-pi',source,{'series_batch':state}))
    loaded=load_setup(target,'quick-pi',source)['state']['series_batch']
    assert validate_state(loaded,inventory())==expected
    for case in loaded['cases']:
        electrical=case['electrical']
        assert len(electrical['series'])==2
        assert all(len(s['parallel'])==1 for s in electrical['series'])
        assert len(electrical['sink_terminals'])==len(electrical['source_terminals'])==2
    source.write_bytes(b'changed revision')
    with pytest.raises(ValueError,match='revision'):load_setup(target,'quick-pi',source)


@pytest.mark.parametrize('voltage,current',[('nan','1'),('3.3','0'),('3.3','inf'),('bad','1')])
def test_invalid_operating_values_are_not_enqueued(voltage,current):
    with pytest.raises(ValueError,match='positive finite'):make_case(path(),inventory(),'case',voltage,current)


def test_duplicate_names_or_missing_pin_reject_whole_setup():
    a=make_case(path(),inventory(),'rail','3.3','2')
    state=dict(schema=SCHEMA,cases=[a,deepcopy(a)],draft=dict(name='',voltage='',current=''))
    with pytest.raises(ValueError,match='unique'):validate_state(state,inventory())
    state['cases'].pop();state['cases'][0]['electrical']['series'][0]['to_pad']='missing'
    with pytest.raises(ValueError):validate_state(json.loads(json.dumps(state)),inventory())


def test_stale_editor_cannot_bind_setup_to_new_board_revision(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from quick_pi_plugin.series_batch_setup import require_current_board
    board=tmp_path/'example.kicad_pcb';board.write_bytes(b'original')
    editor=SimpleNamespace(board_path=str(board),inventory={
        'source_sha256':hashlib.sha256(board.read_bytes()).hexdigest()})
    require_current_board(editor)
    board.write_bytes(b'new revision')
    with pytest.raises(ValueError,match='saved board changed'):require_current_board(editor)
