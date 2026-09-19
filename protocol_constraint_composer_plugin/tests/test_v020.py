"""v0.2 pure-core regressions. These do NOT execute KiCad or wxPython."""
import copy,json,math
import pytest
from conftest import BOARD,PROJECT
from protocol_constraint_composer_plugin.constraint_studio.board import BoardContext
from protocol_constraint_composer_plugin.constraint_studio.model import Constraint,Rule,RuleDocument,numeric,lint
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace,apply_bundle
from protocol_constraint_composer_plugin.constraint_studio.engineering import (builtin_profiles,compile_profile,install_profile,capture_profile,validate_profile,
    matrix_from_csv,matrix_to_csv,timing_budget,length_from_delay,stackup_layers,record_review,review_state,fingerprint)
from protocol_constraint_composer_plugin.constraint_studio.linked_areas import (local_courtyard,stage_attached_area,attached_areas,all_areas,
    area_polygon,check_attached_guard,rebuild_attached_area,equivalent_outline)
from protocol_constraint_composer_plugin.constraint_studio.inspection import (Item,items_from_board,evaluate,enclosed,rule_match,priority_trace,read_drc_report)
from protocol_constraint_composer_plugin.constraint_studio.native_bridge import SelectionBridge,native_items

@pytest.mark.parametrize('v,u,want',[('500ps','length_or_time',500),('1ps + 2ps','length_or_time',3),('100','ps',100),('5mil','length_or_time',.127),('1e3ps','ps',1000),('180deg','deg',180)])
def test_time_numeric(v,u,want):assert numeric(v,u)==pytest.approx(want)
@pytest.mark.parametrize('v,u',[('1ps','mm'),('1mm','ps'),('1mm + 1ps','length_or_time'),('1ps','count'),('1deg','length_or_time'),('1.2','count')])
def test_time_invalid_domains(v,u):
    with pytest.raises(ValueError):numeric(v,u)
@pytest.mark.parametrize('kind',['length','skew'])
def test_native_time_rule_roundtrip(kind):
    d=RuleDocument(rules=[Rule('Timing',constraints=[Constraint(kind,{'min':'450ps','opt':'500ps','max':'550ps'})])])
    assert not any(i.severity=='error' for i in lint(d))
    assert RuleDocument.load(d.emit()).rules[0].constraints[0].values['opt']=='500ps'
@pytest.mark.parametrize('kind',['length','skew'])
def test_native_mixed_time_length_rejected(kind):
    d=RuleDocument(rules=[Rule('Bad',constraints=[Constraint(kind,{'min':'1mm','max':'2ps'})])])
    assert any(i.severity=='error' for i in lint(d))


def profile_bindings(p):
    # Keep fixtures explicit but assert every declared parameter receives a value.
    defaults={'text':'ClassA','layer':'F.Cu','ps':'500ps','mm':'.5mm','count':'2','number':'1'}
    result={k:defaults[v['type']] for k,v in p['parameters'].items()}
    return result

@pytest.mark.parametrize('profile',builtin_profiles(),ids=lambda p:p['id'])
def test_builtin_compile(profile):
    rs,floors=compile_profile(profile,profile_bindings(profile),'Example')
    assert rs and not any(x.severity=='error' for x in lint(RuleDocument(rules=rs)))
    assert '{{' not in RuleDocument(rules=rs).emit()
    assert all('CS-SET Example' in r.notes.splitlines() for r in rs)

def test_profile_no_defaults():
    with pytest.raises(ValueError,match='explicit'):compile_profile(builtin_profiles()[0],{},'Example')
def test_profile_unknown_parameter():
    with pytest.raises(ValueError,match='Unknown'):compile_profile(builtin_profiles()[0],{'oops':'1'},'Example')
def test_profile_escapes_text():
    p=builtin_profiles()[0];b=profile_bindings(p);b['netclass']="a' || B.NetName == 'malicious"
    rs,_=compile_profile(p,b,'X')
    assert "a\\'" in rs[0].condition
    # The entire name remains one function argument, not an OR group.
    from protocol_constraint_composer_plugin.constraint_studio.expressions import parse_expression
    assert parse_expression(rs[0].condition).op=='leaf'
@pytest.mark.parametrize('bad',['__import__("os")','1/0','-1mm','1ps','NaN','${UNRESOLVED}'])
def test_bad_numeric_profile_binding(bad):
    p=builtin_profiles()[0];b=profile_bindings(p);b['width']=bad
    with pytest.raises(ValueError):compile_profile(p,b,'X')
def test_profile_idempotent_and_position(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p)
    install_profile(w,p,b,'Link');w.document.append(Rule('after',constraints=[Constraint('track_width',{'min':'.6mm'})]))
    before=w.document.emit();install_profile(w,p,b,'Link')
    assert w.document.emit()==before and w.document.rules[-1].name=='after'
def test_profile_manual_change_guard(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p);install_profile(w,p,b,'Link')
    w.document.rules[-1].constraints[0].values['min']='.7mm';before=w.state()
    with pytest.raises(ValueError,match='edited manually'):install_profile(w,p,b,'Link')
    assert w.state()==before

def test_profile_version_requires_approval(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p);install_profile(w,p,b,'Link')
    q=copy.deepcopy(p);q['version']='1.1.0';before=w.state()
    with pytest.raises(ValueError,match='migration'):install_profile(w,q,b,'Link')
    assert before==w.state()
    install_profile(w,q,b,'Link',approve_migration=True);assert w.metadata['profile_instances']['Link']['version']=='1.1.0'
def test_profile_same_version_changed_definition_requires_review(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p);install_profile(w,p,b,'Link')
    q=copy.deepcopy(p);q['description']='Different definition'
    with pytest.raises(ValueError,match='migration'):install_profile(w,q,b,'Link')
def test_profile_missing_metadata_not_overwritten(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p);install_profile(w,p,b,'Link');w.metadata.pop('profile_instances')
    with pytest.raises(ValueError,match='ownership'):install_profile(w,p,b,'Link')
def test_manufacturing_floor_opt_in(project):
    w=Workspace.load(project);p=next(p for p in builtin_profiles() if p['floors']);b=profile_bindings(p);before=w.floors.copy()
    install_profile(w,p,b,'Fab',apply_floors=False);assert w.floors==before
    install_profile(w,p,b,'Fab',apply_floors=True);assert w.floors!=before

def test_sidecar_unknown_metadata_persists(project,tmp_path):
    side=project.with_suffix('.constraint-studio.json');side.write_text(json.dumps({'version':'0.1.0','courtyard_guards':[],'external_notes':{'keep':7}}))
    w=Workspace.load(project);p=builtin_profiles()[0];install_profile(w,p,profile_bindings(p),'Link')
    out=w.export_bundle(tmp_path/'review');reloaded=Workspace.load(out/project.name)
    assert reloaded.metadata['external_notes']=={'keep':7}
    install_profile(reloaded,p,profile_bindings(p),'Link')
def test_captured_unknown_constraint_preserved_by_refusal():
    with pytest.raises(ValueError):capture_profile([Rule('R',constraints=[Constraint('future_constraint',{'min':'1mm'})])],'user.set','Set')
@pytest.mark.parametrize('version',['1','v1.2.3','1.02.3','1.0.0-beta'])
def test_profile_bad_versions(version):
    p=builtin_profiles()[0];p['version']=version
    with pytest.raises(ValueError):validate_profile(p)

def test_matrix_csv_roundtrip_blank_zero():
    labels=['Default','HighSpeed'];cells={(0,0):'',(0,1):'0mm',(1,0):'0mm',(1,1):'.2mm'}
    a,b=matrix_from_csv(matrix_to_csv(labels,cells));assert a==labels and b==cells
@pytest.mark.parametrize('csv_text',['class,A,B\nA,,.1mm\nB,.2mm,\n','class,A,B\nA,,.1mm\n','class,A,A\nA,,\nA,,\n','class,A\nA,not-a-number\n'])
def test_matrix_invalid_csv(csv_text):
    with pytest.raises(ValueError):matrix_from_csv(csv_text)
def test_timing_budget():assert timing_budget(1000,100,50,150)['pcb_ps']==700
@pytest.mark.parametrize('args',[(1,2,0,0),(-1,0,0,0),(math.nan,0,0,0),(1,0,-1,0),(math.inf,0,0,0)])
def test_bad_timing_budget(args):
    with pytest.raises(ValueError):timing_budget(*args)
def test_length_estimate():assert length_from_delay(1000,4)==pytest.approx(149.896229)
@pytest.mark.parametrize('delay,er',[(1,0),(-1,4),(1,math.nan),(1,math.inf)])
def test_bad_length_estimate(delay,er):
    with pytest.raises(ValueError):length_from_delay(delay,er)
def test_review_content_stale(project):
    w=Workspace.load(project);record_review(w,'Engineer','Baseline','reviewed');assert review_state(w)=='reviewed'
    w.document.rules[0].name='Changed';assert review_state(w).startswith('stale')
    record_review(w,'Engineer','Update','reviewed');assert w.metadata['reviews'][-1]['previous']==fingerprint(w.metadata['reviews'][0])
def test_review_requires_rationale(project):
    with pytest.raises(ValueError):record_review(Workspace.load(project),'Engineer','')
def test_local_approval_blocked_on_error(project):
    w=Workspace.load(project);w.document.rules[0].constraints[0].values['min']='.01mm'
    with pytest.raises(ValueError,match='errors'):record_review(w,'Engineer','Not valid','approved')

def attached(text=BOARD):
    before=BoardContext.load(text);out,g=stage_attached_area(before,'U1');return BoardContext.load(out),g

def test_attached_inside_footprint_not_board():
    c,g=attached();assert len(c.areas)==1 and len(attached_areas(c))==1
    assert len(c.footprint('U1').node.find('zone'))==1
    assert check_attached_guard(c,g)[0]
    assert area_polygon(attached_areas(c)[0])==[(98,98),(102,98),(102,102),(98,102)]
@pytest.mark.parametrize('pose',['(at 150 80 90)','(at 0 0 180)','(at 10 15 23.4)'])
def test_attached_move_rotate_does_not_stale(pose):
    c,g=attached();moved=BoardContext.load(c.text.replace('(at 100 100 0)',pose));assert check_attached_guard(moved,g)[0]
    assert area_polygon(attached_areas(c)[0])!=area_polygon(attached_areas(moved)[0])
def test_attached_owner_is_uuid_not_reference():
    c,g=attached();renamed=BoardContext.load(c.text.replace('"Reference" "U1"','"Reference" "U99"'));assert check_attached_guard(renamed,g)[0]
def test_attached_detect_courtyard_change():
    c,g=attached();c=BoardContext.load(c.text.replace('(end 2 2)','(end 3 2)'));ok,msg=check_attached_guard(c,g);assert not ok and 'Courtyard' in msg
    out,g2=rebuild_attached_area(c,g);assert check_attached_guard(BoardContext.load(out),g2)[0]
def test_attached_backside_creation():
    text=BOARD.replace('(layer "F.Cu")\n    (uuid','(layer "B.Cu")\n    (uuid',1).replace('F.CrtYd','B.CrtYd')
    c,g=attached(text);assert g['layers']==['B.Cu'] and check_attached_guard(c,g)[0]
def test_attached_simulated_flip_layer_check():
    c,g=attached();fp=c.footprint('U1');block=c.text[fp.node.start:fp.node.end].replace('F.Cu','B.Cu').replace('F.CrtYd','B.CrtYd')
    flipped=BoardContext.load(c.text[:fp.node.start]+block+c.text[fp.node.end:]);assert check_attached_guard(flipped,g)[0]
    # This test simulates a symmetric saved shape, not KiCad's native flip command.
def test_attached_detect_independent_layer_drift():
    c,g=attached();area=attached_areas(c)[0]['node'];block=c.text[area.start:area.end].replace('F.Cu','B.Cu');c=BoardContext.load(c.text[:area.start]+block+c.text[area.end:])
    assert not check_attached_guard(c,g)[0]
def test_attached_detect_keepout_change():
    c,g=attached();a=attached_areas(c)[0]['node'];block=c.text[a.start:a.end].replace('(tracks allowed)','(tracks not_allowed)')
    c=BoardContext.load(c.text[:a.start]+block+c.text[a.end:]);assert not check_attached_guard(c,g)[0]
def test_attached_duplicate_name_refused():
    c,g=attached()
    with pytest.raises(ValueError,match='unique'):stage_attached_area(c,'U1',g['name'])
@pytest.mark.parametrize('shape',['fp_arc','fp_circle'])
def test_attached_curves_refused(shape):
    with pytest.raises(ValueError):attached(BOARD.replace('fp_rect',shape))
def test_attached_apply_bundle(project,tmp_path):
    w=Workspace.load(project);w.board_text,g=stage_attached_area(w.context,'U1');w.guards.append(g);w.refresh_board_context()
    out=w.export_bundle(tmp_path/'review');assert (out/'_apply'/'constraint_studio'/'linked_areas.py').exists()
    apply_bundle(out,True);assert check_attached_guard(BoardContext.load(project.read_text()),g)[0]

def circle(x=100,y=100,r=.15,layer='F.Cu'):return Item('id','Pad',net='N',layers=(layer,),points=[(x,y)],radius=r,geometry='circle',properties={'Type':'Pad','NetName':'N'})
@pytest.mark.parametrize('x,y,r,want',[(100,100,.15,True),(103,100,.15,False),(101.9,100,.15,False),(100,100,2,None),(100,100,1.999,True)])
def test_conservative_enclosure(x,y,r,want):assert enclosed(circle(x,y,r),BoardContext.load(BOARD).areas[0]).value is want

def test_crossing_segment_not_inside():
    i=Item('trace','Track',layers=('F.Cu',),points=[(100,100),(103,100)],radius=.05,geometry='capsule')
    assert enclosed(i,BoardContext.load(BOARD).areas[0]).value is False

def test_curve_unknown():
    i=circle();i.geometry='unknown';assert enclosed(i,BoardContext.load(BOARD).areas[0]).value is None

def test_enclosed_wrong_layer_false():assert enclosed(circle(layer='B.Cu'),BoardContext.load(BOARD).areas[0]).value is False
@pytest.mark.parametrize('expr,want',[("A.Type == 'Pad'",True),("A.Type == 'Via'",False),("A.Type == 'Pad' && A.fromTo('U1-1', 'U2-1')",None),("A.Type == 'Via' && A.fromTo('U1-1', 'U2-1')",False),("A.Type == 'Pad' || A.fromTo('U1-1', 'U2-1')",True),("!A.fromTo('U1-1','U2-1')",None)])
def test_preview_three_valued_logic(expr,want):assert evaluate(expr,circle()).value is want

def test_pair_reversed_and_missing_b():
    a=circle();b=Item('via','Via',layers=('F.Cu',),properties={'Type':'Via'})
    r=Rule('pair',"A.Type == 'Via' && B.Type == 'Pad'",constraints=[Constraint('clearance',{'min':'.2mm'})])
    assert rule_match(r,a,b,pair=True).value is True
    assert rule_match(r,a,pair=True).value is None

def test_unsupported_higher_rule_blocks_native_winner_claim():
    d=RuleDocument(rules=[Rule('fallback',constraints=[Constraint('clearance',{'min':'.2mm'})]),Rule('unknown',"A.memberOfGroup('G')",constraints=[Constraint('clearance',{'min':'.1mm'})])])
    trace=priority_trace(d,'clearance',circle(),circle());assert trace['indeterminate'] and trace['authority']=='offline-subset-preview'
    assert 'higher unknown' in trace['rows'][1]['status']

def test_disabled_rule_not_candidate():
    d=RuleDocument(rules=[Rule('disabled',constraints=[Constraint('clearance',{'min':'.2mm'})],enabled=False)])
    assert priority_trace(d,'clearance',circle(),circle())['candidate'] is None

def test_ignore_still_participates():
    d=RuleDocument(rules=[Rule('ignored',severity='ignore',constraints=[Constraint('clearance',{'min':'.2mm'})])])
    t=priority_trace(d,'clearance',circle(),circle());assert t['candidate']==0 and t['rows'][0]['severity']=='ignore'

def test_items_and_class_membership():
    items=items_from_board(BoardContext.load(BOARD),PROJECT);pad=next(i for i in items if i.kind=='Pad')
    assert evaluate("A.hasNetclass('HighSpeed')",pad).value is True
    assert evaluate("A.hasNetclass('Other')",pad).value is None
    assert evaluate("A.getField('Reference') == 'U1'",pad).value is None
    assert evaluate("A.memberOfFootprint('U1')",pad).value is True

def test_noncircular_rotated_pad_not_certified():
    text=BOARD.replace('smd circle','smd rect').replace('(at 100 100 0)','(at 100 100 90)');items=items_from_board(BoardContext.load(text),PROJECT)
    assert all(i.geometry=='unknown' for i in items if i.kind=='Pad')

def test_native_report_sections_and_uuids():
    data={'violations':[{'type':'clearance','severity':'error','description':'Native description','items':[{'uuid':'id'}],'rule':'rule one'}],'unconnected_items':[]}
    rows=read_drc_report(data);assert rows[0]['uuids']==['id'] and rows[0]['rule']=='rule one'
    assert rows[0]['native_record']==data['violations'][0]
@pytest.mark.parametrize('data',[{},[],{'violations':5}])
def test_bad_report(data):
    with pytest.raises(ValueError):read_drc_report(data)

class UID:
    def __init__(self,s):self.s=s
    def AsString(self):return self.s
class MockItem:
    def __init__(self,key):self.m_Uuid=UID(key);self.selected=False
    def IsSelected(self):return self.selected
    def SetSelected(self):self.selected=True
    def ClearSelected(self):self.selected=False
class MockBoard:
    def __init__(self,path):self.path=str(path);self.stamp=1;self.items=[MockItem('a'),MockItem('b')]
    def GetFileName(self):return self.path
    def GetTimeStamp(self):return self.stamp
    def GetFootprints(self):return []
    def GetTracks(self):return self.items
    def GetZoneList(self,include):assert include;return []

def test_native_bridge_all_or_nothing(tmp_path):
    b=MockBoard(tmp_path/'demo.kicad_pcb');b.items[0].selected=True;bridge=SelectionBridge(lambda:b,lambda:None)
    with pytest.raises(ValueError):bridge.probe(['missing'])
    assert bridge.selection()==['a'];bridge.probe(['b']);assert bridge.selection()==['b']
def test_native_bridge_stale_board_blocked(tmp_path):
    b=MockBoard(tmp_path/'demo.kicad_pcb');bridge=SelectionBridge(lambda:b,lambda:None);b.stamp+=1
    with pytest.raises(RuntimeError,match='changed'):bridge.probe(['a'])
def test_native_bridge_other_project_blocked(tmp_path):
    b=MockBoard(tmp_path/'demo.kicad_pcb');bridge=SelectionBridge(lambda:b,lambda:None);b.path=str(tmp_path/'other.kicad_pcb')
    with pytest.raises(RuntimeError,match='Active board'):bridge.selection()

def test_disabling_profile_rule_is_manual_edit(project):
    w=Workspace.load(project);p=builtin_profiles()[0];b=profile_bindings(p);install_profile(w,p,b,'Link');w.document.rules[-1].enabled=False
    with pytest.raises(ValueError,match='edited manually'):install_profile(w,p,b,'Link')

def test_profile_capture_parameterizes_values_scope_and_layer():
    from protocol_constraint_composer_plugin.constraint_studio.engineering import profile_slots,parameterize_profile
    r=Rule('R',"A.hasNetclass('Original')",layer='F.Cu',constraints=[Constraint('track_width',{'min':'.15mm','opt':'.2mm'})])
    p=capture_profile([r],'user.set','Set');slots=profile_slots(p)
    binding={i:{'name':'p'+str(i),'type':slot['type']} for i,slot in enumerate(slots)}
    q=parameterize_profile(p,binding)
    values={('p'+str(i)):slot['value'] for i,slot in enumerate(slots)}
    rs,_=compile_profile(q,values,'New instance')
    assert rs[0].condition==r.condition and rs[0].layer=='F.Cu' and numeric(rs[0].constraints[0].values['min'])==.15
    assert not p['parameters']

def test_profile_capture_shared_parameter_defaults_consistent():
    from protocol_constraint_composer_plugin.constraint_studio.engineering import parameterize_profile
    p=capture_profile([Rule('R',constraints=[Constraint('track_width',{'min':'.15mm','opt':'.2mm'})])],'user.set','Set')
    shared={0:{'name':'width','type':'mm'},1:{'name':'width','type':'mm'}}
    q=parameterize_profile(p,shared);assert len(q['parameters'])==1
    with pytest.raises(ValueError,match='consistent'):parameterize_profile(p,shared,use_defaults=True)

def test_profile_capture_defaults_optin():
    from protocol_constraint_composer_plugin.constraint_studio.engineering import parameterize_profile
    p=capture_profile([Rule('R',constraints=[Constraint('track_width',{'min':'.15mm'})])],'user.set','Set')
    q=parameterize_profile(p,{0:{'name':'width','type':'mm'}},use_defaults=True)
    assert compile_profile(q,{},'Applied')[0][0].constraints[0].values['min']=='0.15mm'

def test_via_span_contains_inner_layers():
    text=BOARD.replace('(31 "B.Cu" signal)','(2 "In1.Cu" signal) (4 "In2.Cu" signal) (31 "B.Cu" signal)')
    via='(via (at 100 100) (size .6) (drill .3) (layers "F.Cu" "B.Cu") (net 1) (uuid "v"))'
    text=text.rstrip()[:-1]+via+')';items=items_from_board(BoardContext.load(text),PROJECT)
    assert next(i for i in items if i.kind=='Via').layers==('F.Cu','In1.Cu','In2.Cu','B.Cu')

def test_saved_stackup_read():
    text=BOARD.replace('(general (thickness 1.6))','(general (thickness 1.6)) (setup (stackup (layer "F.Cu" (type "copper") (thickness .035)) (layer "dielectric 1" (type "core") (thickness 1.53) (material "FR4") (epsilon_r 4.2) (loss_tangent .02))))')
    rows=stackup_layers(BoardContext.load(text));assert rows[1]['epsilon_r']=='4.2' and rows[1]['material']=='FR4'

def test_null_netclass_assignments_do_not_crash_snapshot():
    p=copy.deepcopy(PROJECT);p['net_settings']['netclass_assignments']=None;p['net_settings']['netclass_patterns']=None
    pads=[i for i in items_from_board(BoardContext.load(BOARD),p) if i.kind=='Pad']
    assert pads and pads[0].netclasses is None

def test_boolean_function_comparison_never_ignored():
    assert evaluate("A.existsOnLayer('F.Cu') == 0",circle()).value is None

def test_no_field_null_semantics_are_invented():
    item=Item('f','Footprint',fields={})
    assert evaluate("A.getField('MISSING') == ''",item).value is None

def test_gui_source_has_no_cross_dialog_page_method():
    from pathlib import Path
    import ast
    root=Path(__file__).parents[1]/'constraint_studio'
    for name in ('ui.py','workbench_ui.py'):
        tree=ast.parse((root/name).read_text(encoding='utf-8'),feature_version=(3,10))
        for cls in [n for n in tree.body if isinstance(n,ast.ClassDef)]:
            defined={x.name for x in cls.body if isinstance(x,ast.FunctionDef)}
            called={n.func.attr for n in ast.walk(cls) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='self' and n.func.attr[:1].islower()}
            assert called-defined <= {'native_select','pick'}


def test_csv_unresolved_variables_are_not_assumed_equal():
    with pytest.raises(ValueError,match='Asymmetric'):matrix_from_csv('object,A,B\nA,,${A}\nB,${B},\n')

def test_csv_negative_clearance_rejected():
    with pytest.raises(ValueError,match='nonnegative'):matrix_from_csv('object,A\nA,-.2mm\n')
