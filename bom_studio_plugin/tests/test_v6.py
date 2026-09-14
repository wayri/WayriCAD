"""Engineering library, qualification, approvals, independent variants and allocations.
All component identities and declarations here are synthetic, not manufacturer facts.
"""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
import io,json,os,shutil,tempfile,unittest,zipfile,sqlite3,time
from test_core import Fixture
from bomstudio import partsdb as p,engineering as e,governance as g,qualification as q,variantlab as v,masslib as m,buildplan as b,cli,intelligence,analytics,automation,enforcement
from bomstudio.engine import Workspace
from bomstudio.native import BASE,Project,sha
from bomstudio.sexpr import parse,properties
from bomstudio.writeback import compile_plan,apply_plan

class EngFixture(Fixture):
 def setUp(self):
  super().setUp();self.lib=p.Library(self.dir/'catalog',create=True)
 def tearDown(self):self.lib.close();super().tearDown()
 def part(self,ref='R1',**extra):
  row=self.row(ref);fields={k:str(x) for k,x in row['fields'].items() if k not in p.PROTECTED};fields.update(extra)
  request={'new':True,'fields':fields,'reference_hint':ref};plan=e.part_preview(self.lib,request)
  return e.part_apply(self.lib,plan,'CATALOG','Tester','Synthetic fixture creation')['part']
 def revise(self,part,**kw):
  plan=e.part_preview(self.lib,{'id':part['id'],'expected_revision':part['revision'],**kw});return e.part_apply(self.lib,plan,'CATALOG','Tester','Reviewed synthetic update')['part']
 def footprint(self):
  folder=self.dir/'libraries/Resistor_SMD.pretty';folder.mkdir(parents=True,exist_ok=True);file=folder/'R_0603_1608Metric.kicad_mod'
  file.write_text('(footprint "R_0603_1608Metric" (version 20241229) (layer "F.Cu") (solder_mask_margin 0) (solder_paste_margin 0) (solder_paste_margin_ratio 0)\n (pad "1" smd rect (at -0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask"))\n (pad "2" smd rect (at 0.8 0) (size 0.9 1) (layers "F.Cu" "F.Paste" "F.Mask")))')
  intelligence.configure(self.ws,{'library_roots':[str(folder.parent)]});return file
 def spec(self):
  self.footprint();row=self.row('R1');pins=__import__('bomstudio.footprints',fromlist=['symbol_pins']).symbol_pins(self.ws.project.by_id[row['id']])
  pads=[{k:x for k,x in a.items() if k!='custom'} for a in q.actual_geometry(self.dir/'libraries/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod')['pads']]
  return {'schema':'wayricad-land-pattern-1','manufacturer':row['fields']['Manufacturer'],'mpn':row['fields']['MPN'],'source_url':'https://example.com/synthetic-drawing','document_revision':'TEST ONLY','document_sha256':'a'*64,'page':1,'reviewed_by':'Synthetic test author','frame':'top-view-mm','tolerance_mm':.02,'angle_tolerance_deg':.1,'pads':pads,'pin_functions':{k:[n] for k,n in pins['pin_names'].items()}}
 def accounts(self):
  g.register(self.lib,'Admin','admin','test-admin-passphrase','REGISTER')
  g.register(self.lib,'Engineer','engineering','test-eng-passphrase','REGISTER','Admin','test-admin-passphrase')
  g.register(self.lib,'Buyer','supply','test-buyer-passphrase','REGISTER','Admin','test-admin-passphrase')
 def decision(self,ctx,**kw):
  d={'kind':'release','reviewer':'Engineer','password':'test-eng-passphrase','role':'engineering','reason':'Reviewed synthetic engineering context','evidence':'TEST RECORD','target':'','expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),'input_hash':ctx['input_hash'],'confirmation':'REVIEW'};d.update(kw)
  return g.decide(self.lib,self.ws,BASE,d,ctx['policy'])
 def evidence(self,part,stock=1000,**extra):
  record={'manufacturer':part['fields']['Manufacturer'],'mpn':part['fields']['MPN'],'supplier':'DigiKey','sku':'TEST-SKU','stock':stock,'region':'IN','source_url':'https://example.com/test-observation','observed_at':datetime.now(timezone.utc).isoformat(),'reviewed':True,**extra}
  plan=e.evidence_preview(self.lib,part['id'],record);return e.evidence_apply(self.lib,plan,'IMPORT','Tester')['part']

class CatalogTests(EngFixture):
 def test_empty_created(self):self.assertEqual(self.lib.info()['parts'],0);self.assertTrue(self.lib.verify()['ok'])
 def test_existing_create_refused(self):
  with self.assertRaises(FileExistsError):p.Library(self.lib.root,create=True)
 def test_exact_identity_case_suffix(self):
  a={'Manufacturer':' TEST Inc ','MPN':'ABC-TR'};self.assertEqual(p.record_identity(a),p.record_identity({'Manufacturer':'test inc','MPN':'ABC-TR'}));self.assertNotEqual(p.record_identity(a),p.record_identity({'Manufacturer':'TEST Inc','MPN':'abc-tr'}))
 def test_revision_history(self):
  x=self.part();y=self.revise(x,fields={'Tolerance':'1%'});self.assertEqual(y['revision'],2);self.assertNotIn('Tolerance',self.lib.get(x['id'],1)['fields']);self.assertEqual(len(self.lib.history(x['id'])),2)
 def test_revision_is_stale(self):
  x=self.part();plan=e.part_preview(self.lib,{'id':x['id'],'expected_revision':1,'status':'preferred'});self.revise(x,tags=['changed'])
  with self.assertRaises(ValueError):e.part_apply(self.lib,plan,'CATALOG','T','Long enough reason')
 def test_no_identity_rename(self):
  x=self.part()
  with self.assertRaises(ValueError):self.revise(x,fields={'MPN':'DIFFERENT'})
 def test_no_approval_flag(self):
  x=self.part();x['qualified']=True
  with self.assertRaises(ValueError):self.lib.put(x,'T','unsafe')
 def test_duplicate_ipn(self):
  x=self.part()
  with self.assertRaises(ValueError):e.part_preview(self.lib,{'new':True,'internal_pn':x['internal_pn'],'fields':{'Manufacturer':'Other','MPN':'Other'}})
 def test_fts_custom_metadata(self):
  x=self.part(Subsystem='PayloadA',Temp_Max='125');self.assertEqual(self.lib.search('PayloadA')['items'][0]['id'],x['id'])
 def test_ipn_search(self):
  x=self.part();self.assertEqual(self.lib.search(x['internal_pn'])['total'],1)
 def test_fts_punctuation_not_sql(self):
  self.part();self.assertEqual(self.lib.search('";DROP TABLE parts;--')['total'],0);self.assertEqual(self.lib.info()['parts'],1)
 def test_export_no_credentials(self):
  self.accounts();s=p.encoded(self.lib.snapshot());self.assertNotIn('password',s);self.assertNotIn('review_key',s);self.assertNotIn('test-admin',s)
 def test_integrity_detects_payload_tamper(self):
  x=self.part();self.lib.db.execute('UPDATE parts SET payload=? WHERE id=?',(p.encoded({**x,'notes':'tampered'}),x['id']));self.assertFalse(self.lib.verify()['ok'])
 def test_transaction_rollback(self):
  with self.assertRaises(RuntimeError):
   with self.lib.transaction():self.lib.touch();raise RuntimeError()
  self.assertEqual(self.lib.meta('epoch'),'0')
 def test_harvest_read_only_and_import(self):
  before={f:sha(f.read_bytes()) for f in self.dir.glob('*.kicad_*')};plan=p.harvest([str(self.path)],capture_assets=False);self.assertGreater(len(plan['parts']),0);self.assertEqual(self.lib.info()['parts'],0)
  r=p.import_harvest(self.lib,plan,'IMPORT','Tester');self.assertGreater(r['count'],0);self.assertEqual(before,{f:sha(f.read_bytes()) for f in before})
 def test_harvest_cancellation(self):
  with self.assertRaises(InterruptedError):p.harvest([str(self.path)],cancel=lambda:True)
  self.assertEqual(self.lib.info()['parts'],0)
 def test_harvest_stale_source(self):
  plan=p.harvest([str(self.path)]);self.path.write_text(self.path.read_text()+'\n')
  with self.assertRaises(ValueError):p.import_harvest(self.lib,plan,'IMPORT','Tester')
  self.assertEqual(self.lib.info()['parts'],0)
 def test_harvest_idempotent(self):
  plan=p.harvest([str(self.path)]);p.import_harvest(self.lib,plan,'IMPORT','Tester');self.assertEqual(p.import_harvest(self.lib,plan,'IMPORT','Tester')['count'],0)
 def test_asset_native_bundle_parser(self):
  self.footprint();self.ws.save();plan=p.harvest([str(self.path)]);p.import_harvest(self.lib,plan,'IMPORT','Tester');pid=p.record_identity(self.row('R1')['fields']);raw,name,mime=p.export_native_library(self.lib,[pid]);self.assertEqual(mime,'application/zip')
  with zipfile.ZipFile(io.BytesIO(raw)) as z:
   self.assertIsNone(z.testzip());symname=next(n for n in z.namelist() if n.endswith('.kicad_sym'));tree=parse(z.read(symname).decode());self.assertEqual(tree.tag,'kicad_symbol_lib');self.assertEqual(len(tree.nodes('symbol')),1);self.assertTrue(any(n.endswith('.kicad_mod') for n in z.namelist()))
 def test_native_export_without_assets_refuses(self):
  x=self.part()
  with self.assertRaises(ValueError):p.export_native_library(self.lib,[x['id']])
 def test_evidence_lifecycle_kept_on_stale(self):
  x=self.evidence(self.part(),lifecycle='NRND',observed_at='2020-01-01T00:00:00Z');h=p.catalog_health(x);self.assertEqual(h['lifecycle'],'AT RISK');self.assertEqual(h['stock']['status'],'unknown')
 def test_low_stock_warn(self):
  x=self.evidence(self.part(),stock=2);h=p.catalog_health(x);self.assertTrue(h['low_stock']);self.assertEqual(h['state'],'warning')
 def test_evidence_future_unknown(self):
  x=self.evidence(self.part(),observed_at='2099-01-01T00:00:00Z');self.assertEqual(p.catalog_health(x)['stock']['status'],'unknown')
 def test_evidence_exact_mpn(self):
  x=self.part()
  with self.assertRaises(ValueError):self.evidence(x,mpn='WRONG')
 def test_no_automatic_lifecycle_network(self):
  x=self.part();h=p.catalog_health(x);self.assertEqual(h['lifecycle'],'UNKNOWN');self.assertEqual(h['stock']['status'],'unknown')
 def test_recommendation_case_pattern(self):
  x=self.part(Value='10000');r=p.recommendations(self.lib,self.ws,BASE,self.row('R1')['id']);self.assertTrue(r['items']);self.assertFalse(r['items'][0]['automatic_substitution'])
 def test_recommendation_rating_conflict(self):
  self.edit('R1',{'Voltage':'50'});x=self.part(Voltage='25');r=p.recommendations(self.lib,self.ws,BASE,self.row('R1')['id']);self.assertEqual(r['items'][0]['state'],'blocked')
 def test_recommend_nrnd_refused(self):
  x=self.evidence(self.part(),lifecycle='NRND')
  with self.assertRaises(ValueError):e.recommend_preview(self.lib,self.ws,BASE,self.row('R1')['id'],x['id'])
 def test_recommend_review_ack(self):
  x=self.part();plan=e.recommend_preview(self.lib,self.ws,BASE,self.row('R1')['id'],x['id'])
  with self.assertRaises(ValueError):e.recommend_apply(self.lib,self.ws,BASE,plan,'EDIT',False,False)
  e.recommend_apply(self.lib,self.ws,BASE,plan,'EDIT',False,True);self.assertEqual(self.row('R1')['fields']['CatalogID'],x['id'])

class IndependentVariantTests(EngFixture):
 def make(self,name='Procurement',mode='derived',parent=BASE):v.apply(self.ws,v.preview(self.ws,{'op':'create','name':name,'mode':mode,'parent':parent}),'VARIANT')
 def test_derived_inherits(self):self.make();self.edit('R1',{'Value':'12k'});self.assertEqual(self.row('R1','Procurement')['fields']['Value'],'12k')
 def test_pinned_fields_keep_old(self):
  old=self.row('R1')['fields']['Value'];self.make(mode='pinned');self.edit('R1',{'Value':'12k'});self.assertEqual(self.row('R1','Procurement')['fields']['Value'],old)
 def test_bomonly_does_not_native_sync(self):
  self.make();self.edit('R1',{'Value':'SPECIAL'},'Procurement');self.native_apply();self.assertIn('Procurement',self.ws.state['variants']);self.assertNotIn('Procurement',Project(self.path).variant_descriptions);self.assertEqual(self.row('R1','Procurement')['fields']['Value'],'SPECIAL');self.assertNotIn('SPECIAL',self.ws.project.root.read_text())
 def test_bomonly_variables_do_not_block_native(self):
  self.make();self.ws.set_variables('variant',{'LocalCost':'3'},'Procurement');self.native_apply();self.assertEqual(self.ws.variables('Procurement')['LocalCost'],'3')
 def test_locked_edit_refused(self):
  self.make();v.apply(self.ws,v.preview(self.ws,{'op':'lock','name':'Procurement'}),'VARIANT')
  with self.assertRaises(ValueError):self.edit('R1',{'Value':'13k'},'Procurement')
 def test_rename_reparents_children(self):
  self.make();self.make('Child',parent='Procurement');v.apply(self.ws,v.preview(self.ws,{'op':'rename','name':'Procurement','new':'Budget'}),'VARIANT');self.assertEqual(self.ws.state['variants']['Child']['parent'],'Budget')
 def test_cycle_rejected(self):
  self.make();self.make('Child',parent='Procurement')
  with self.assertRaises(ValueError):v.preview(self.ws,{'op':'reparent','name':'Procurement','parent':'Child'})
 def test_native_parent_blocked(self):
  self.make();self.ws.state['variants']['Procurement']['bom_only']=False;self.ws.state['variants']['Procurement']['parent']='Other';self.ws.state['variants']['Other']={'parent':BASE,'native':False,'bom_only':True,'overrides':{},'variables':{}}
  with self.assertRaises(ValueError):self.ws._validate_state()
 def test_stale_variant_plan(self):
  plan=v.preview(self.ws,{'op':'create','name':'P'});self.edit('R1',{'Test':'change'})
  with self.assertRaises(ValueError):v.apply(self.ws,plan,'VARIANT')
 def test_variant_one_undo(self):self.make();self.ws.undo();self.assertNotIn('Procurement',self.ws.state['variants'])
 def test_invalid_tags_rejected(self):
  with self.assertRaises(ValueError):v.preview(self.ws,{'op':'create','name':'P','tags':{'x':'notalist'}})

class QualificationTests(EngFixture):
 def test_health_settings_can_be_updated(self):
  intelligence.configure(self.ws,{'stock_age_hours':24});intelligence.configure(self.ws,{'stock_age_hours':48});self.assertEqual(self.ws.state['health_settings']['stock_age_hours'],48)
 def test_declared_geometry_match(self):
  spec=self.spec();r=q.run(self.ws,BASE,self.row('R1')['id'],spec);self.assertEqual(r['status'],'MATCHED_DECLARED_CHECKS',r['issues'])
 def test_wrong_pad_position(self):
  s=self.spec();s['pads'][0]['x']+=.3;self.assertEqual(q.run(self.ws,BASE,self.row('R1')['id'],s)['status'],'MISMATCH')
 def test_wrong_pin_function(self):
  s=self.spec();s['pin_functions']['1']=['WRONG'];self.assertEqual(q.run(self.ws,BASE,self.row('R1')['id'],s)['status'],'MISMATCH')
 def test_missing_pin_functions_unknown(self):
  s=self.spec();s['pin_functions']={};self.assertEqual(q.run(self.ws,BASE,self.row('R1')['id'],s)['status'],'INCOMPLETE')
 def test_implicit_mask_not_pass(self):
  s=self.spec();s['pads'][0].pop('mask_margin');self.assertEqual(q.run(self.ws,BASE,self.row('R1')['id'],s)['status'],'INCOMPLETE')
 def test_unknown_mpn_rejected(self):
  s=self.spec();s['mpn']='Wrong'
  with self.assertRaises(ValueError):q.run(self.ws,BASE,self.row('R1')['id'],s)
 def test_outline_frame_rejected(self):
  s=self.spec();s['frame']='bottom-view'
  with self.assertRaises(ValueError):q.validate_spec(s)
 def test_missing_source_rejected(self):
  s=self.spec();s.pop('document_sha256')
  with self.assertRaises(ValueError):q.validate_spec(s)
 def test_missing_source_locator_rejected(self):
  s=self.spec();s.pop('page')
  with self.assertRaises(ValueError):q.validate_spec(s)
 def test_negative_and_nan_geometry_rejected(self):
  for k,val in [('width',-1),('x',float('nan')),('rotation',float('inf'))]:
   s=self.spec();s['pads'][0][k]=val
   with self.subTest(k=k),self.assertRaises(ValueError):q.validate_spec(s)
 def test_hash_changes_geometry(self):
  s=self.spec();a=q.run(self.ws,BASE,self.row('R1')['id'],s)['fingerprint'];file=self.dir/'libraries/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod';file.write_text(file.read_text()+'\n');self.assertNotEqual(a,q.run(self.ws,BASE,self.row('R1')['id'],s)['fingerprint'])
 def test_same_hash_different_time(self):
  s=self.spec();self.assertEqual(q.run(self.ws,BASE,self.row('R1')['id'],s)['fingerprint'],q.run(self.ws,BASE,self.row('R1')['id'],s)['fingerprint'])

class GovernanceTests(EngFixture):
 def setUp(self):super().setUp();self.accounts()
 def test_admin_cannot_sign_engineering(self):
  ctx=g.context(self.lib,self.ws)
  with self.assertRaises(ValueError):self.decision(ctx,reviewer='Admin',password='test-admin-passphrase')
 def test_password_not_stored(self):
  dump=' '.join(str(tuple(r)) for r in self.lib.db.execute('SELECT * FROM reviewers'));self.assertNotIn('test-admin-passphrase',dump)
 def test_wrong_password_rejected(self):
  with self.assertRaises(ValueError):g.authenticate(self.lib,'Engineer','wrong-passphrase')
 def test_review_pass_and_stale_edit(self):
  ctx=g.context(self.lib,self.ws);self.decision(ctx);self.assertEqual(g.assess(self.lib,ctx)['status'],'APPROVED_LOCAL');self.edit('R1',{'Note':'Changed'});now=g.assess(self.lib,g.context(self.lib,self.ws));self.assertEqual(now['status'],'NOT_APPROVED');self.assertEqual(now['decisions'][0]['status'],'STALE')
 def test_view_change_does_not_invalidate(self):
  ctx=g.context(self.lib,self.ws);self.ws.state['view']['columns']=['Reference'];self.assertEqual(ctx['input_hash'],g.context(self.lib,self.ws)['input_hash'])
 def test_catalog_change_invalidates(self):
  ctx=g.context(self.lib,self.ws);self.part();self.assertNotEqual(ctx['input_hash'],g.context(self.lib,self.ws)['input_hash'])
 def test_geometry_change_invalidates(self):
  file=self.footprint();ctx=g.context(self.lib,self.ws);file.write_text(file.read_text()+'\n');self.assertNotEqual(ctx['input_hash'],g.context(self.lib,self.ws)['input_hash'])
 def test_two_roles_required(self):
  ctx=g.context(self.lib,self.ws,policy={'roles':['engineering','supply']});self.decision(ctx);self.assertEqual(g.assess(self.lib,ctx)['missing_roles'],['supply']);self.decision(ctx,reviewer='Buyer',password='test-buyer-passphrase',role='supply');self.assertEqual(g.assess(self.lib,ctx)['status'],'APPROVED_LOCAL')
 def test_errors_not_waivable(self):
  self.edit('R1',{'MPN':''});self.ws.state['settings']['required_fields']=['MPN'];ctx=g.context(self.lib,self.ws,policy={'check_level':'warning'});errs=[x for x in ctx['issues'] if x['severity']=='error']
  if not errs:self.edit('R1',{'Value':'${UNRESOLVED}'});ctx=g.context(self.lib,self.ws);errs=[x for x in ctx['issues'] if x['severity']=='error']
  self.assertTrue(errs)
  with self.assertRaises(ValueError):self.decision(ctx,kind='waiver',target=errs[0]['id'])
 def test_unknown_scoped_waiver(self):
  ctx=g.context(self.lib,self.ws,policy={'catalog_required':True});issue=next(i for i in ctx['issues'] if i['code']=='NO_CATALOG');self.decision(ctx,kind='waiver',target=issue['id']);self.assertNotIn(issue['id'],[i['id'] for i in g.assess(self.lib,ctx)['unwaived_issues']])
 def test_waiver_needs_evidence(self):
  ctx=g.context(self.lib,self.ws,policy={'catalog_required':True});issue=next(i for i in ctx['issues'] if i['code']=='NO_CATALOG')
  with self.assertRaises(ValueError):self.decision(ctx,kind='waiver',target=issue['id'],evidence='')
 def test_expiry_no_future(self):
  with self.assertRaises(ValueError):self.decision(g.context(self.lib,self.ws),expires_at='2020-01-01T00:00:00Z')
 def test_signature_tamper_detected(self):
  self.decision(g.context(self.lib,self.ws));self.lib.db.execute("UPDATE decisions SET signature='bad'");self.assertEqual(g.ledger(self.lib)[0]['status'],'INVALID')
 def test_deactivate_reviewer_invalidates(self):
  ctx=g.context(self.lib,self.ws);self.decision(ctx);g.deactivate(self.lib,'Engineer','Admin','test-admin-passphrase','DEACTIVATE');self.assertEqual(g.assess(self.lib,ctx)['status'],'NOT_APPROVED')
 def test_last_admin_cannot_remove(self):
  with self.assertRaises(ValueError):g.deactivate(self.lib,'Admin','Admin','test-admin-passphrase','DEACTIVATE')
 def test_qualification_requires_actual_match(self):
  ctx=g.context(self.lib,self.ws)
  with self.assertRaises(ValueError):self.decision(ctx,kind='qualification',target='made-up')
 def test_native_run_gate_blocks_without_review(self):
  c=automation.default_pipeline();c['variants']=[BASE];c['reports']=['checks'];c['formats']=['json'];c['release_control']={'library':str(self.lib.root)};out=self.dir/'run';r=automation.pipeline(self.ws,c,out);self.assertEqual(r['status'],'FAILED');self.assertFalse(any('BOM_Demo__' in p.name for p in out.rglob('*')))
 def test_native_run_gate_passes_with_review(self):
  self.decision(g.context(self.lib,self.ws));c=automation.default_pipeline();c.update(variants=[BASE],reports=['checks'],formats=['json'],release_control={'library':str(self.lib.root)});self.assertEqual(automation.pipeline(self.ws,c,self.dir/'run')['status'],'PASSED')

class MassTests(EngFixture):
 def test_suggestion_is_not_auto_edit(self):
  raw=self.ws._serialize();r=m.suggest(self.ws);self.assertTrue(r['items']);self.assertEqual(raw,self.ws._serialize())
 def test_existing_zero_not_overwritten(self):
  self.edit('R1',{'Mass':'0'});self.assertNotIn(self.row('R1')['id'],[r['id'] for r in m.suggest(self.ws)['items']])
 def test_existing_unknown_not_overwritten(self):
  self.edit('R1',{'Mass':'unknown'});self.assertNotIn(self.row('R1')['id'],[r['id'] for r in m.suggest(self.ws)['items']])
 def test_accept_estimate_metadata(self):
  r=next(x for x in m.suggest(self.ws)['items'] if x['reference']=='R1');plan=m.preview(self.ws,BASE,[{'id':r['id'],'option':r['options'][0]['id']}]);m.apply(self.ws,BASE,plan,'EDIT',True);self.assertIn('estimated',self.row('R1')['fields']['Mass_Basis']);self.assertTrue(self.row('R1')['fields']['Mass_Source'])
 def test_acknowledgement_required(self):
  x=m.suggest(self.ws)['items'][0];plan=m.preview(self.ws,BASE,[{'id':x['id'],'option':x['options'][0]['id']}])
  with self.assertRaises(ValueError):m.apply(self.ws,BASE,plan,'EDIT',False)
 def test_stale_existing_mass(self):
  x=m.suggest(self.ws)['items'][0];plan=m.preview(self.ws,BASE,[{'id':x['id'],'option':x['options'][0]['id']}]);self.ws.edit([x['id']],BASE,{'Mass':'1g'})
  with self.assertRaises(ValueError):m.apply(self.ws,BASE,plan,'EDIT',True)
 def test_no_universal_sot23_five_pin_proxy(self):
  row=deepcopy(self.row('R1'));row['ref']='Q1';row['fields']['Footprint']='Package_TO_SOT_SMD:SOT-23-5'
  with patch.object(self.ws,'rows',return_value=[row]):self.assertFalse(m.suggest(self.ws)['items'])
 def test_exact_catalog_preferred(self):
  x=self.part(Mass='0.009g',Mass_Source='Measured test record');r=next(x for x in m.suggest(self.ws,lib=self.lib)['items'] if x['reference']=='R1');self.assertTrue(r['options'][0]['id'].startswith('catalog-'));self.assertEqual(r['options'][0]['mass'],'0.009 g')
 def test_every_seed_has_source_and_assumptions(self):
  for s in m.seeds():self.assertTrue(s['source'].startswith('https://'));self.assertTrue(s['assumptions']);self.assertTrue(s['range'])
 def test_mlcc_height_choices(self):
  r=next(x for x in m.suggest(self.ws)['items'] if x['reference']=='C1');self.assertGreaterEqual(len(r['options']),2)

class PurchasingTests(EngFixture):
 def setUp(self):
  super().setUp();self.x=self.part();cid=self.row('R1')['id']
  self.ws.edit([r['id'] for r in self.ws.rows() if r['id']!=cid],BASE,{'in_bom':False});self.clock=datetime.now(timezone.utc)
 def config(self,n=10,offers=None,**kw):return {'schema':'wayricad-build-plan-1','builds':[{'id':'A','boards':n}], 'offers':offers or [],**kw}
 def offer(self,**kw):return {'id':'Offer1','part_id':self.x['id'],'supplier':'DigiKey','sku':'SKU1','pool_id':'POOL1','available':100,'observed_at':self.clock.isoformat(),'source_url':'https://example.com/stock','region':'IN','reviewed':True,'lead_days':0,'currency':'INR','unit_price':'2','moq':1,'multiple':1,'tiers':[],**kw}
 def lot(self,n=100,**kw):
  row={'id':'Lot1','part_id':self.x['id'],'quantity':n,'reserved':0,'location':'A','source':'Test physical count','observed_at':self.clock.isoformat(),**kw};plan=b.inventory_preview(self.lib,[row]);b.inventory_apply(self.lib,plan,'INVENTORY','Tester')
 def test_inventory_covers_no_write(self):
  self.lot(10);before=self.lib.snapshot();r=b.run(self.ws,self.lib,self.config(),self.clock);self.assertEqual(r['demands'][0]['shortfall'],0);self.assertFalse(r['orders']);self.assertEqual(before,self.lib.snapshot())
 def test_double_build_no_double_inventory(self):
  self.lot(10);c=self.config();c['builds'].append({'id':'B','boards':10});r=b.run(self.ws,self.lib,c,self.clock);self.assertEqual(sum(x['inventory_used'] for x in r['demands']),10);self.assertEqual(sum(x['shortfall'] for x in r['demands']),10)
 def test_reserved_excluded(self):self.lot(10,reserved=5);self.assertEqual(b.run(self.ws,self.lib,self.config(),self.clock)['demands'][0]['shortfall'],5)
 def test_quarantine_excluded(self):self.lot(10,status='quarantine');self.assertEqual(b.run(self.ws,self.lib,self.config(),self.clock)['demands'][0]['shortfall'],10)
 def test_order_moq_multiple(self):
  r=b.run(self.ws,self.lib,self.config(10,[self.offer(moq=25,multiple=10)]),self.clock);self.assertEqual(r['orders'][0]['quantity'],30);self.assertEqual(r['known_cost_by_currency'],{'INR':'60'})
 def test_price_tier(self):
  r=b.run(self.ws,self.lib,self.config(20,[self.offer(tiers=[{'min_qty':20,'unit_price':'1.5'}])]),self.clock);self.assertEqual(r['known_cost_by_currency'],{'INR':'30.0'})
 def test_pool_not_added(self):
  offers=[self.offer(available=6),self.offer(id='Offer2',sku='SKU2',available=6)];r=b.run(self.ws,self.lib,self.config(10,offers,allow_split=True,independent_pools_reviewed=True),self.clock);self.assertEqual(r['demands'][0]['shortfall'],4)
 def test_split_requires_review(self):
  with self.assertRaises(ValueError):b.validate_config(self.config(allow_split=True))
 def test_split_two_independent_pools(self):
  offers=[self.offer(available=6),self.offer(id='Offer2',sku='SKU2',pool_id='POOL2',available=6)];r=b.run(self.ws,self.lib,self.config(10,offers,allow_split=True,independent_pools_reviewed=True),self.clock);self.assertEqual(r['demands'][0]['shortfall'],0);self.assertEqual(len(r['orders']),2)
 def test_split_disabled_cannot_combine(self):
  offers=[self.offer(available=6),self.offer(id='Offer2',sku='SKU2',pool_id='POOL2',available=6)];self.assertEqual(b.run(self.ws,self.lib,self.config(10,offers),self.clock)['demands'][0]['shortfall'],10)
 def test_future_stock_excluded(self):
  r=b.run(self.ws,self.lib,self.config(10,[self.offer(observed_at=(self.clock+timedelta(days=1)).isoformat())]),self.clock);self.assertEqual(r['demands'][0]['shortfall'],10)
 def test_wrong_market_excluded(self):
  self.assertEqual(b.run(self.ws,self.lib,self.config(10,[self.offer(region='US')]),self.clock)['demands'][0]['shortfall'],10)
 def test_unknown_lead_does_not_cover_date(self):
  c=self.config(10,[self.offer(lead_days=None)]);c['builds'][0]['due_date']=(self.clock+timedelta(days=7)).date().isoformat();self.assertEqual(b.run(self.ws,self.lib,c,self.clock)['demands'][0]['shortfall'],10)
 def test_purchased_surplus_reused(self):
  c=self.config(10,[self.offer(moq=30)]);c['builds'].append({'id':'B','boards':10});r=b.run(self.ws,self.lib,c,self.clock);self.assertEqual(len(r['orders']),1);self.assertEqual(sum(d['shortfall'] for d in r['demands']),0)
 def test_no_unknown_source_offer(self):
  with self.assertRaises(ValueError):b.validate_config(self.config(10,[self.offer(source_url='')]))
 def test_unresolved_variables_block(self):
  self.edit('R1',{'Value':'${MISSING}'})
  with self.assertRaises(ValueError):b.run(self.ws,self.lib,self.config(),self.clock)
 def test_stale_inventory_plan(self):
  plan=b.inventory_preview(self.lib,[]);self.revise(self.x,tags=['changed'])
  with self.assertRaises(ValueError):b.inventory_apply(self.lib,plan,'INVENTORY','Tester')
 def test_unknown_inventory_part_refuses(self):
  with self.assertRaises(ValueError):b.inventory_preview(self.lib,[{'id':'X','part_id':'no-part','quantity':1}])

class EngineeringCLITests(EngFixture):
 def cmd(self,args):
  stdout=io.StringIO();stderr=io.StringIO()
  with redirect_stdout(stdout),redirect_stderr(stderr):code=cli.main(args)
  return code,stdout.getvalue(),stderr.getvalue()
 def test_help_all_families(self):
  for name in cli.ENGINEERING_COMMANDS:
   with self.subTest(name=name),redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as cm:cli.main([name,'--help'])
   self.assertEqual(cm.exception.code,0)
 def test_catalog_info_json(self):
  code,out,err=self.cmd(['catalog','info','--library',str(self.lib.root)]);self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['parts'],0)
 def test_catalog_verify_json(self):self.assertEqual(self.cmd(['catalog','verify','--library',str(self.lib.root)])[0],0)
 def test_harvest_json(self):
  code,out,err=self.cmd(['catalog','harvest',str(self.path),'--metadata-only']);self.assertEqual(code,0,err);self.assertTrue(json.loads(out)['data']['parts'])
 def test_mass_suggestion_json(self):
  code,out,err=self.cmd(['mass','suggest',str(self.path)]);self.assertEqual(code,0,err);self.assertTrue(json.loads(out)['data']['items'])
 def test_no_output_overwrite(self):
  out=self.dir/'result';out.write_text('KEEP');code,_,_=self.cmd(['catalog','info','--library',str(self.lib.root),'--output',str(out)]);self.assertEqual(code,4);self.assertEqual(out.read_text(),'KEEP')
 def test_host_not_available(self):
  with patch('shutil.which',return_value=None):code,out,err=self.cmd(['hosttest','--directory',str(self.dir/'host')])
  self.assertEqual(code,6,err);self.assertEqual(json.loads(out)['data']['status'],'UNAVAILABLE')
 def test_cli_password_not_accepted_flag(self):
  code,out,err=self.cmd(['review','register','--library',str(self.lib.root),'--name','Admin','--role','admin','--confirm','REGISTER','--password','should-not-echo-secret']);self.assertEqual(code,2)

if __name__=='__main__':unittest.main()
