"""Executed core tests. These are explicitly NOT native KiCad acceptance."""
import copy,json,math
import pytest
from conftest import BOARD,PROJECT
from protocol_constraint_composer_plugin.constraint_studio.board import BoardContext
from protocol_constraint_composer_plugin.constraint_studio.courtyards import (stage_regions,courtyard_contours,scope_for_regions,check_regions,sync_workspace,Edge)
from protocol_constraint_composer_plugin.constraint_studio.linked_areas import all_areas
from protocol_constraint_composer_plugin.constraint_studio.sexpr import scalar
from protocol_constraint_composer_plugin.constraint_studio.workspace import Workspace
from protocol_constraint_composer_plugin.constraint_studio.model import Rule,Constraint,RuleDocument
from protocol_constraint_composer_plugin.constraint_studio.engineering import builtin_profiles
from protocol_constraint_composer_plugin.constraint_studio import team,topology,field_solver

RECT='(fp_rect (start -2 -2) (end 2 2) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'

def ctx(shape=RECT):return BoardContext.load(BOARD.replace(RECT,shape))
def ws():return Workspace(context=ctx(),board_text=BOARD,project=copy.deepcopy(PROJECT))
def managed(shape=RECT,auto=True):
    w=ws();w.context=ctx(shape);w.board_text=w.context.text
    w.board_text,g=stage_regions(w.context,'U1',auto_sync=auto);w.refresh_board_context()
    a,b=scope_for_regions(g['regions'],'A'),scope_for_regions(g['regions'],'B')
    r=Rule('BGA',f'({a}) && ({b})',constraints=[Constraint('clearance',{'min':'.12mm'})]);g['rule_names']=[r.name];g['rule_states']=[r.state()]
    w.document=RuleDocument(rules=[r]);w.guards=[g];return w

@pytest.mark.parametrize('shape',[
    RECT,'(fp_circle (center 0 0) (end 2 0) (layer "F.CrtYd"))',
    '(fp_arc (start -2 0) (mid 0 -2) (end 2 0) (layer "F.CrtYd"))(fp_line (start 2 0) (end -2 0) (layer "F.CrtYd"))',
    RECT+'(fp_rect (start 3 -2) (end 5 2) (layer "F.CrtYd"))',
    RECT+'(fp_circle (center 0 0) (end 1 0) (layer "F.CrtYd"))',
])
def test_regions_roundtrip_exact(shape):
    w=managed(shape);assert check_regions(w.context,w.guards[0])[0]=='current';assert not [x for x in w.issues() if x.severity=='error']
    if 'fp_arc' in shape or 'fp_circle' in shape:assert '(pts (arc' in w.board_text

def test_nested_holes_are_explicit_exclusions():
    w=managed(RECT+'(fp_circle (center 0 0) (end 1 0) (layer "F.CrtYd"))');s=scope_for_regions(w.guards[0]['regions']);assert '!A.intersectsArea' in s

def test_move_does_not_rewrite_local_contour():
    w=managed();w.board_text=w.board_text.replace('(at 100 100 0)','(at 50 130 90)');w.refresh_board_context();assert check_regions(w.context,w.guards[0])[0]=='current'

@pytest.mark.parametrize('shape',[
    '(fp_line (start 0 0) (end 1 0) (layer "F.CrtYd"))',
    RECT+'(fp_rect (start 1 1) (end 3 3) (layer "F.CrtYd"))',
    '(fp_circle (center 0 0) (end 0 0) (layer "F.CrtYd"))',
    '(fp_poly (pts (xy 0 0)(xy 2 2)(xy 0 2)(xy 2 0)) (layer "F.CrtYd"))',
])
def test_invalid_courtyards_rejected(shape):
    with pytest.raises(ValueError):stage_regions(ctx(shape),'U1')

def test_automatic_regeneration_and_rules_preserved():
    w=managed();w.board_text=w.board_text.replace(RECT,RECT.replace('end 2 2','end 3 2'));w.refresh_board_context()
    assert check_regions(w.context,w.guards[0])[0]=='stale';assert sync_workspace(w);assert check_regions(w.context,w.guards[0])[0]=='current'

def test_auto_sync_opt_out():
    w=managed(auto=False);w.board_text=w.board_text.replace(RECT,RECT.replace('end 2 2','end 3 2'));w.refresh_board_context();assert not sync_workspace(w);assert sync_workspace(w,True)

def test_sync_preserves_manual_rule_edits():
    w=managed();w.board_text=w.board_text.replace(RECT,RECT.replace('end 2 2','end 3 2'));w.refresh_board_context();w.document.rules[0].enabled=False;before=w.state()
    with pytest.raises(ValueError,match='edited'):sync_workspace(w)
    assert w.state()==before

def test_sync_refuses_independent_area_edit():
    w=managed();w.board_text=w.board_text.replace('(xy 2.000000000 2.000000000)','(xy 3.000000000 2.000000000)');w.refresh_board_context()
    assert check_regions(w.context,w.guards[0])[0]=='invalid'
    with pytest.raises(ValueError):sync_workspace(w,True)

def test_circle_arc_geometry_sagitta():
    samples=Edge((-1,0),(1,0),(0,1)).samples(.001);assert all(abs(math.hypot(*p)-1)<1e-8 for p in samples);assert max(y for x,y in samples)>.999

def test_catalog_roundtrip_pin(tmp_path):
    c=team.SharedCatalog(tmp_path);p=builtin_profiles()[0];key,digest=c.publish(p);w=ws();team.pin_profile(w,c,key,digest)
    assert team.synchronization_plan(w,c)[0]['status']=='current';assert c.get(key,digest)==p

def test_catalog_version_immutable(tmp_path):
    c=team.SharedCatalog(tmp_path);p=copy.deepcopy(builtin_profiles()[0]);c.publish(p);p['description']='Changed'
    with pytest.raises(ValueError,match='immutable'):c.publish(p)

def test_catalog_tamper(tmp_path):
    c=team.SharedCatalog(tmp_path);key,digest=c.publish(builtin_profiles()[0]);(tmp_path/'objects'/(digest+'.json')).write_text('{}')
    with pytest.raises(ValueError,match='checksum'):c.get(key)

def test_catalog_lock(tmp_path):
    c=team.SharedCatalog(tmp_path)
    with team.catalog_lock(tmp_path):
        with pytest.raises(RuntimeError):c.publish(builtin_profiles()[0])

@pytest.mark.parametrize('url',['http://example.com','https://a:b@example.com','https://example.com?token=x','file:///tmp'])
def test_https_catalog_rejects_unsafe_roots(url):
    with pytest.raises(ValueError):team.HTTPSCatalog(url)

@pytest.fixture
def identity():
    pytest.importorskip('cryptography');private,public=team.generate_identity('test passphrase only 123')
    return private,public,{team.key_id(public):{'public_key':public.decode(),'principal':'Engineer','roles':['approver']}}

def signed(identity):
    private,public,trust=identity;w=ws();team.sign_review(w,private,'test passphrase only 123','Engineer','Test fixture');return w,trust

def test_crypto_verified(identity):
    w,trust=signed(identity);assert team.verify_reviews(w,trust)['approved']

def test_crypto_unknown_key(identity):
    w,_=signed(identity);assert not team.verify_reviews(w,{})['approved']

def test_crypto_content_stale(identity):
    w,trust=signed(identity);w.project['unrelated']['foo'][0]=999;report=team.verify_reviews(w,trust);assert not report['approved'];assert report['records'][0]['status']=='stale'

def test_crypto_payload_tamper(identity):
    w,trust=signed(identity);w.metadata['signed_reviews'][0]['body']['rationale']='Forged';assert not team.verify_reviews(w,trust)['approved']

def test_crypto_distinct_approval(identity):
    w,trust=signed(identity);team.sign_review(w,identity[0],'test passphrase only 123','Engineer','Second');assert not team.verify_reviews(w,trust,2)['approved']

def test_crypto_rejection_overrides(identity):
    w,trust=signed(identity);team.sign_review(w,identity[0],'test passphrase only 123','Engineer','Reject','rejected');assert not team.verify_reviews(w,trust)['approved']

def test_crypto_not_approver(identity):
    w,trust=signed(identity)
    for t in trust.values():t['roles']=[]
    assert not team.verify_reviews(w,trust)['approved']

def test_crypto_private_encrypted(identity):assert b'BEGIN ENCRYPTED PRIVATE KEY' in identity[0]

TOPO='''(kicad_pcb (version 20241229)(layers (0 "F.Cu" signal))
(footprint "TX" (layer "F.Cu")(property "Reference" "U1")(pad "1" smd rect (net 1 "N1")))
(footprint "RX" (layer "F.Cu")(property "Reference" "U2")(pad "2" smd rect (net 2 "N2")))
(footprint "R" (layer "F.Cu")(property "Reference" "R1")(pad "1" smd rect (net 1 "N1"))(pad "2" smd rect (net 2 "N2"))))'''
BR=[{'from':'R1-1','to':'R1-2','delay_ps':10}]

def test_logical_path():
    p=topology.series_path(BoardContext.load(TOPO),'U1-1','U2-2',BR);assert len(p['segments'])==2;assert p['component_delay_ps']==10

def test_logical_bridge_not_guessed():
    with pytest.raises(ValueError,match='No path'):topology.series_path(BoardContext.load(TOPO),'U1-1','U2-2',[])

def test_path_native_rules():
    rules,p=topology.compile_path(BoardContext.load(TOPO),'U1-1','U2-2',BR,100,10,[30,40],'Clock');assert len(rules)==2;assert p['reserve_ps']==10;assert all('fromTo' in r.condition and 'ps' in r.constraints[0].values['max'] for r in rules)

def test_path_exceeds_budget():
    with pytest.raises(ValueError,match='exceeds'):topology.compile_path(BoardContext.load(TOPO),'U1-1','U2-2',BR,100,10,[70,40],'Clock')

def test_path_different_component_bridge_rejected():
    with pytest.raises(ValueError,match='same component'):topology.series_path(BoardContext.load(TOPO),'U1-1','U2-2',[{'from':'U1-1','to':'U2-2'}])

@pytest.mark.parametrize('nx,ny,er',[(11,11,1),(21,15,4),(9,19,2.5)])
def test_field_solver_parallel_plate_analytic(nx,ny,er):
    fixed={j*nx+i:j/(ny-1) for j in range(ny) for i in range(nx) if i in (0,nx-1) or j in (0,ny-1)}
    energy,p,it,res=field_solver.electrostatic(nx,ny,.002,.001,[er]*(nx*ny),fixed)
    assert energy==pytest.approx(field_solver.EPS0*er*2,rel=1e-7)
    assert max(abs(p[j*nx+i]-j/(ny-1)) for j in range(ny) for i in range(nx))<1e-6

def test_solver_cancel():
    nx=ny=11;fixed={j*nx+i:float(j==10) for j in range(ny) for i in range(nx) if i in (0,10) or j in (0,10)}
    with pytest.raises(field_solver.Cancelled):field_solver.electrostatic(nx,ny,1,1,[1.]*121,fixed,cancel=lambda:True)

def test_solver_homogeneous_dielectric_scaling():
    a=field_solver.uniform_line(.6,.2,1,kind='stripline',nx=41,ny=21);b=field_solver.uniform_line(.6,.2,4,kind='stripline',nx=41,ny=21)
    assert b.impedance_ohm==pytest.approx(a.impedance_ohm/2,rel=1e-6);assert b.effective_permittivity==pytest.approx(4,rel=1e-7)

@pytest.mark.parametrize('params',[(0,.2,4),(.1,-1,4),(.1,.2,.5),(.1,float('nan'),4)])
def test_solver_invalid(params):
    with pytest.raises(ValueError):field_solver.uniform_line(*params)


def test_crypto_truncation_anchor(identity):
    w,trust=signed(identity);team.sign_review(w,identity[0],'test passphrase only 123','Engineer','Reject','rejected')
    head=team.sha(team.canonical(w.metadata['signed_reviews'][-1]));w.metadata['signed_reviews'].pop()
    assert not team.verify_reviews(w,trust,expected_head=head)['approved']

def test_external_policy_apply(project,tmp_path,identity):
    w=Workspace.load(project);w.document.append(Rule('Added',constraints=[Constraint('track_width',{'min':'.3mm'})]))
    record=team.sign_review(w,identity[0],'test passphrase only 123','Engineer','Approve fixture')
    d=w.export_bundle(tmp_path/'review_policy');policy=tmp_path/'admin_policy.json'
    policy.write_text(json.dumps({'schema':1,'trusted_keys':identity[2],'required_approvals':1,'expected_review_head':team.sha(team.canonical(record)),'require_anti_rollback_anchor':True}))
    backup,r=team.apply_with_policy(d,policy,True);assert backup and r['approved']

def test_untrusted_bundle_policy_refused(project,tmp_path,identity):
    w=Workspace.load(project);d=w.export_bundle(tmp_path/'review_untrusted');p=d/'policy.json';p.write_text('{}')
    with pytest.raises(ValueError,match='outside'):team.apply_with_policy(d,p,True)

def test_acceptance_form_samples():
    from protocol_constraint_composer_plugin.constraint_studio.acceptance import sample_constraint
    from protocol_constraint_composer_plugin.constraint_studio.catalog import SPECS
    from protocol_constraint_composer_plugin.constraint_studio.model import lint
    for spec in SPECS:assert not [x for x in lint(RuleDocument(rules=[Rule(spec.key,constraints=[sample_constraint(spec)])])) if x.severity=='error']

@pytest.mark.parametrize('data,code,text,expected',[(None,0,'',False),({},0,'',True),({},5,'',True),({},2,'',False),({},0,'Error parsing rules',False),({},5,'Syntax error',False)])
def test_acceptance_reports_are_not_faked(data,code,text,expected):
    from protocol_constraint_composer_plugin.constraint_studio.acceptance import accepted_drc
    assert accepted_drc({'data':data,'returncode':code,'stderr':text})==expected


def test_curved_fp_polygon_source():
    shape='(fp_poly (pts (arc (start -2 0)(mid 0 2)(end 2 0))(arc (start 2 0)(mid 0 -2)(end -2 0))) (layer "F.CrtYd"))'
    w=managed(shape);assert check_regions(w.context,w.guards[0])[0]=='current'

def test_contour_order_change_is_not_stale():
    hole='(fp_circle (center 0 0) (end 1 0) (layer "F.CrtYd"))';w=managed(RECT+hole);w.board_text=w.board_text.replace(RECT+hole,hole+RECT);w.refresh_board_context()
    assert check_regions(w.context,w.guards[0])[0]=='current'

def test_native_bridge_uses_actual_selection(tmp_path):
    from test_v020 import MockBoard
    from protocol_constraint_composer_plugin.constraint_studio.native_bridge import SelectionBridge,uuid_text
    b=MockBoard(tmp_path/'demo.kicad_pcb');b.items[0].selected=True
    bridge=SelectionBridge(lambda:b,lambda:None,get_selection=lambda:[b.items[1]])
    assert bridge.selection()==[uuid_text(b.items[1])]

def test_native_bridge_focus_hook(tmp_path):
    from test_v020 import MockBoard
    from protocol_constraint_composer_plugin.constraint_studio.native_bridge import SelectionBridge,uuid_text
    b=MockBoard(tmp_path/'demo.kicad_pcb');called=[];bridge=SelectionBridge(lambda:b,lambda:None,focus=called.append)
    bridge.probe([uuid_text(b.items[0])]);assert called==[b.items[0]]

def test_solver_stdlib_and_accelerated_agree(monkeypatch):
    import sys
    n=11;fixed={j*n+i:j/(n-1) for j in range(n) for i in range(n) if i in (0,n-1) or j in (0,n-1)}
    args=(n,n,.002,.001,[3.]*(n*n),fixed)
    fast=field_solver.electrostatic(*args)
    monkeypatch.setitem(sys.modules,'numpy',None);slow=field_solver.electrostatic(*args)
    assert fast[0]==pytest.approx(slow[0],rel=1e-9);assert fast[1]==pytest.approx(slow[1],abs=1e-7)

def test_uniform_line_pair_symmetry():
    r=field_solver.uniform_line(.3,.2,4,gap_mm=.3,kind='stripline',nx=41,ny=21)
    nx,ny=r.grid
    assert r.impedance_ohm>0;assert r.effective_permittivity==pytest.approx(4,rel=1e-7)
    assert max(abs(r.potential[j*nx+i]+r.potential[j*nx+(nx-1-i)]) for j in range(ny) for i in range(nx))<1e-6


def test_pair_scope_does_not_bridge_islands():
    from protocol_constraint_composer_plugin.constraint_studio.courtyards import pair_scope
    regions=[{'name':'Island1','parent':None},{'name':'Island2','parent':None}]
    s=pair_scope(regions);terms=s.split(' || ')
    assert len(terms)==2
    assert 'Island1' in terms[0] and 'Island2' not in terms[0]
    assert 'Island2' in terms[1] and 'Island1' not in terms[1]
    assert all('A.enclosedByArea' in x and 'B.enclosedByArea' in x for x in terms)
