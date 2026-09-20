import copy, json, pathlib, subprocess
import pytest
from protocol_constraint_composer_plugin.constraint_studio.board import BoardContext, courtyard_polygon,stage_courtyard_area
from protocol_constraint_composer_plugin.constraint_studio.profiles import bga_rules,matrix_rules,replace_generated
from protocol_constraint_composer_plugin.constraint_studio.model import RuleDocument,Rule,Constraint
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace,apply_bundle,parse_scalar,flatten_scalars,set_path,get_path
from protocol_constraint_composer_plugin.constraint_studio.validation import native_drc
from conftest import BOARD,PROJECT

def test_board_context():
    c=BoardContext.load(BOARD);assert c.footprint('U1').value=='EXAMPLE_ONLY';assert c.areas[0]['rule_area'];assert 'BGA_D0' in c.nets

def test_courtyard_exact():assert courtyard_polygon(BoardContext.load(BOARD),'U1')==[(98,98),(102,98),(102,102),(98,102)]

def test_courtyard_rotation():
    c=BoardContext.load(BOARD.replace('(at 100 100 0)','(at 100 100 90)'))
    assert courtyard_polygon(c,'U1')==pytest.approx([(98,102),(98,98),(102,98),(102,102)])

def test_back_courtyard_refused():
    c=BoardContext.load(BOARD.replace('(layer "F.Cu")\n    (uuid','(layer "B.Cu")\n    (uuid',1))
    with pytest.raises(ValueError,match='front-side'):courtyard_polygon(c,'U1')

def test_arc_refused():
    c=BoardContext.load(BOARD.replace('fp_rect','fp_arc'))
    with pytest.raises(ValueError,match='fp_arc'):courtyard_polygon(c,'U1')

def test_area_creation_preserves_original():
    c=BoardContext.load(BOARD);out,guard=stage_courtyard_area(c,'U1','CS_U1')
    assert c.text==BOARD;new=BoardContext.load(out)
    assert [x['name'] for x in new.areas]==['EXISTING_ESCAPE','CS_U1']
    assert guard['fingerprint']==c.fingerprint('U1')
    assert new.footprint('U1').uid==c.footprint('U1').uid

def test_duplicate_area_refused():
    with pytest.raises(ValueError,match='already exists'):stage_courtyard_area(BoardContext.load(BOARD),'U1','EXISTING_ESCAPE')

def test_bga_strict_a_and_b():
    rs=bga_rules('U1','.1mm','.1mm','.4mm','.2mm',area='CS_U1')
    assert len(rs)==2
    assert rs[0].condition=="(A.enclosedByArea('CS_U1') && B.enclosedByArea('CS_U1'))"
    assert rs[1].condition=="A.enclosedByArea('CS_U1')"
    assert [c.kind for c in rs[1].constraints]==['track_width','via_diameter','hole_size']

def test_bga_dynamic_labelled():
    r=bga_rules('U1','.1mm',mode='intersection')[0]
    assert 'NOT strict' in r.notes;assert 'intersectsCourtyard' in r.condition

def test_matrix_blank_not_zero():
    r=matrix_rules(['Default','HS'],{(0,0):'',(0,1):'.2mm',(1,1):''});assert len(r)==1
    assert "A.hasNetclass('Default')" in r[0].condition and "B.hasNetclass('HS')" in r[0].condition

def test_matrix_zero_is_explicit():assert len(matrix_rules(['A'],{(0,0):'0mm'}))==1

def test_matrix_symmetric():
    with pytest.raises(ValueError,match='Asymmetric'):matrix_rules(['A','B'],{(0,1):'.1mm',(1,0):'.2mm'})

def test_matrix_idempotent_replace():
    d=RuleDocument(rules=[Rule('before'),Rule('after')]);rs=matrix_rules(['A'],{(0,0):'.2mm'})
    replace_generated(d,rs,'CS-MATRIX Main');out=d.emit();replace_generated(d,matrix_rules(['A'],{(0,0):'.2mm'}),'CS-MATRIX Main')
    assert d.emit()==out and len(d.rules)==3

def test_workspace_noop_project_preserved(project):
    w=Workspace.load(project);assert not w.dirty
    assert '.kicad_pro' not in w.changes() and '.kicad_pcb' not in w.changes() and not w.changes()

def test_export_leaves_source_untouched(project,tmp_path):
    original={p.name:p.read_bytes() for p in project.parent.iterdir() if p.is_file()}
    w=Workspace.load(project);w.document.rules[0].constraints[0].values['min']='.3mm';out=w.export_bundle(tmp_path/'review')
    assert all((project.parent/n).read_bytes()==b for n,b in original.items())
    assert (out/'demo.kicad_pcb').read_bytes()==project.read_bytes();assert '0.3mm' in (out/'REVIEW.diff').read_text() # native lexer requires leading zero
    assert '.3mm' in (out/'REVIEW.diff').read_text()

def test_export_disallows_source_directory(project):
    w=Workspace.load(project)
    with pytest.raises(ValueError,match='separate'):w.export_bundle(project.parent)

def test_export_disallows_existing_data(project,tmp_path):
    w=Workspace.load(project);out=tmp_path/'review';out.mkdir();(out/'keep.txt').write_text('keep')
    with pytest.raises(ValueError,match='empty'):w.export_bundle(out)
    assert (out/'keep.txt').read_text()=='keep'

def test_external_change_detected(project):
    w=Workspace.load(project);project.with_suffix('.kicad_dru').write_text('(version 1)')
    with pytest.raises(RuntimeError,match='changed'):w.verify_originals()

def test_apply_requires_closed(project,tmp_path):
    w=Workspace.load(project);out=w.export_bundle(tmp_path/'review')
    with pytest.raises(RuntimeError,match='closed'):apply_bundle(out)

def test_apply_checks_export_hash(project,tmp_path):
    w=Workspace.load(project);out=w.export_bundle(tmp_path/'review');(out/'demo.kicad_dru').write_text('(version 1)')
    with pytest.raises(ValueError,match='changed after export'):apply_bundle(out,True)

def test_apply_checks_source_hash(project,tmp_path):
    w=Workspace.load(project);out=w.export_bundle(tmp_path/'review');project.write_text(BOARD+'\n')
    with pytest.raises(RuntimeError,match='Source changed'):apply_bundle(out,True)

def test_apply_backup(project,tmp_path):
    original=project.with_suffix('.kicad_dru').read_bytes();w=Workspace.load(project);w.document.rules[0].name='Renamed'
    out=w.export_bundle(tmp_path/'review');backup=apply_bundle(out,True)
    assert (backup/'demo.kicad_dru').read_bytes()==original
    assert 'Renamed' in project.with_suffix('.kicad_dru').read_text()
    assert (backup/'journal.json').exists()

def test_apply_rejects_lint_error(project,tmp_path):
    w=Workspace.load(project);w.document.rules[0].constraints[0].values['min']='.01mm';out=w.export_bundle(tmp_path/'review')
    with pytest.raises(ValueError,match='lint errors'):apply_bundle(out,True)

def test_apply_rejects_lock(project,tmp_path):
    w=Workspace.load(project);out=w.export_bundle(tmp_path/'review');(project.parent/'~demo.kicad_pcb.lck').write_text('locked')
    with pytest.raises(RuntimeError,match='lock'):apply_bundle(out,True)

def test_project_unknown_fields_preserved(project,tmp_path):
    w=Workspace.load(project);w.project['net_settings']['classes'][0]['clearance']=.4
    out=w.export_bundle(tmp_path/'review');pro=json.loads((out/'demo.kicad_pro').read_text())
    assert pro['unrelated']==PROJECT['unrelated'];assert pro['net_settings']['classes'][0]['custom_preserve_me']=='untouched'

def test_stale_footprint_guard(project):
    w=Workspace.load(project);w.board_text,g=stage_courtyard_area(w.context,'U1','CS_U1');w.guards.append(g);w.refresh_board_context()
    assert not any(x.severity=='error' for x in w.issues())
    w.board_text=w.board_text.replace('(at 100 100 0)','(at 101 100 0)');w.refresh_board_context()
    assert any('STALE' in x.message for x in w.issues())

@pytest.mark.parametrize('text,old,result',[('true',False,True),('false',True,False),('5',2,5),('.1',1.,.1),('null',None,None),('.4',None,.4),('hello','old','hello')])
def test_settings_types(text,old,result):assert parse_scalar(text,old)==result

def test_settings_reject_nonfinite():
    with pytest.raises(ValueError):parse_scalar('nan',0.)

def test_paths_preserved():
    pro=copy.deepcopy(PROJECT);path=('unrelated','foo',2,'keep');set_path(pro,path,False);assert get_path(pro,path) is False
    assert dict(flatten_scalars(pro))[path] is False

def test_native_cli_no_fake_pass(monkeypatch,tmp_path):
    from protocol_constraint_composer_plugin.constraint_studio import validation
    board=tmp_path/'p.kicad_pcb';board.write_text(BOARD)
    monkeypatch.setattr(validation,'find_cli',lambda explicit='':'kicad-cli')
    seen=[]
    def fake(command,**kwargs):
        seen.append((command,kwargs));return subprocess.CompletedProcess(command,5,'violations','')
    monkeypatch.setattr(validation.subprocess,'run',fake)
    result=native_drc(board)
    assert result['returncode']==5 and result['data'] is None
    assert '--exit-code-violations' in seen[0][0] and '--refill-zones' in seen[0][0]
    assert not seen[0][1].get('shell',False)

def test_area_guard_detects_change(project):
    w=Workspace.load(project);w.board_text,g=stage_courtyard_area(w.context,'U1','CS_U1');w.guards.append(g);w.refresh_board_context()
    w.board_text=w.board_text.replace('(xy 98.000000000 98.000000000)','(xy 97 98)');w.refresh_board_context()
    assert any(x.severity=='error' and 'geometry' in x.message for x in w.issues())

def test_refresh_copied_area(project):
    from protocol_constraint_composer_plugin.constraint_studio.board import refresh_copied_area
    w=Workspace.load(project);w.board_text,g=stage_courtyard_area(w.context,'U1','CS_U1');w.refresh_board_context()
    w.board_text=w.board_text.replace('(at 100 100 0)','(at 101 100 0)');w.refresh_board_context()
    text,new=refresh_copied_area(w.context,g);c=BoardContext.load(text)
    assert c.area_fingerprint('CS_U1')==new['area_fingerprint']
    assert new['area_uuid']==g['area_uuid']
    assert new['fingerprint']!=g['fingerprint']
    assert len([a for a in c.areas if a['name']=='CS_U1'])==1

def test_fingerprint_whitespace_invariant():
    c=BoardContext.load(BOARD);other=BoardContext.load(BOARD.replace('(start -2 -2)','(start -2.000  -2.0)'))
    assert c.fingerprint('U1')==other.fingerprint('U1')

def test_undo_snapshot_isolates_edits(project):
    w=Workspace.load(project);clone=w.clone();clone.project['net_settings']['classes'][0]['clearance']=.5
    clone.document.rules[0].name='Changed'
    assert clone.context is w.context
    assert w.project['net_settings']['classes'][0]['clearance']==.2
    assert w.document.rules[0].name!='Changed'

def test_export_carries_offline_gui(project,tmp_path):
    w=Workspace.load(project);out=w.export_bundle(tmp_path/'review')
    assert (out/'Apply Review.cmd').exists()
    assert (out/'Apply Review.pyw').exists()
    assert (out/'_apply/constraint_studio/offline_gui.py').exists()

def test_apply_rolls_back_multi_file_error(project,tmp_path,monkeypatch):
    from protocol_constraint_composer_plugin.constraint_studio import workspace
    w=Workspace.load(project);w.document.rules[0].name='Changed';w.project['net_settings']['classes'][0]['clearance']=.3
    original=project.with_suffix('.kicad_dru').read_bytes();out=w.export_bundle(tmp_path/'review')
    real=workspace.atomic_write
    def fail(path,data):
        if pathlib.Path(path)==project.with_suffix('.kicad_pro'):raise OSError('Simulated full disk')
        return real(path,data)
    monkeypatch.setattr(workspace,'atomic_write',fail)
    with pytest.raises(OSError,match='Simulated'):workspace.apply_bundle(out,True)
    assert project.with_suffix('.kicad_dru').read_bytes()==original

def test_region_matrix_has_both_enclosures():
    rules=matrix_rules(['Pad','Track'],{(0,1):'.12mm'},scope='type',region='ESCAPE')
    assert "A.enclosedByArea('ESCAPE')" in rules[0].condition and "B.enclosedByArea('ESCAPE')" in rules[0].condition
