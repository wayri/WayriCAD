"""v0.4 shared-query, transactional-automation and fake-IPC contract tests.
IPC tests inject a driver: they are NOT tests against a KiCad host.
"""
from copy import deepcopy
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import io,json,os,shutil,subprocess,sys,threading,unittest,uuid,zipfile
from test_core import Fixture
from bomstudio import actions,automation,bulkedit,cli,configedit,search
from bomstudio.bridge import Bridge,BridgeUnavailable,SelectionService,document_identity,identifier,symbol_path
from bomstudio.engine import Workspace
from bomstudio.native import BASE,Project,sha

class SearchTests(Fixture):
 def refs(self,q,case=False):return search.run(self.ws,BASE,q,case)['references']
 def test_blank_all(self):self.assertEqual(len(self.refs('')),11)
 def test_boolean_precedence(self):self.assertEqual(self.refs('Reference=R1 OR Reference=R2 AND Value=missing'),['R1'])
 def test_parentheses_not(self):self.assertEqual(self.refs('(Reference=R1 OR Reference=R2) AND NOT Value=missing'),['R1','R2'])
 def test_implicit_and(self):self.assertEqual(self.refs('Reference~"R*" Value=10k'),['R1','R2','R3'])
 def test_quotes_and_case(self):
  self.edit('R1',{'Team Label':'Hello \\"quoted" world'})
  self.assertEqual(self.refs('"Team Label":"HELLO"'),['R1']);self.assertEqual(self.refs('"Team Label":"HELLO"',True),[])
 def test_case_sensitive_fields(self):
  with self.assertRaises(ValueError):self.refs('value=10k')
 def test_has_missing_custom(self):
  self.edit('R1',{'Custom X':'a'});self.assertEqual(self.refs('has:"Custom X"'),['R1']);self.assertEqual(len(self.refs('missing:"Custom X"')),10)
 def test_raw_resolved(self):
  self.ws.set_variables('project',{'NOMINAL':'10k'},BASE);self.edit('R1',{'Value':'${NOMINAL}'})
  self.assertIn('R1',self.refs('Value=10k'));self.assertEqual(self.refs('raw.Value="${NOMINAL}"'),['R1']);self.assertIn('R1',self.refs('is:variable'))
 def test_population_states(self):
  self.ws.set_population([self.row('R1')['id']],BASE,'DNI');self.assertEqual(self.refs('is:dni'),['R1']);self.assertNotIn('R1',self.refs('is:fit'))
 def test_numeric_comparisons_no_guessed_units(self):
  self.edit('R1',{'UnitPrice':'2.25'});self.edit('R2',{'UnitPrice':'unknown'})
  self.assertIn('R1',self.refs('UnitPrice>=2'));self.assertNotIn('R2',self.refs('UnitPrice>=2'))
  for q in ('Value>10k','UnitPrice>NaN','UnitPrice>Infinity'):
   with self.subTest(q=q),self.assertRaises(ValueError):self.refs(q)
 def test_glob_has_only_star_question(self):
  self.assertEqual(self.refs('Reference~"R?"'),['R1','R2','R3','R4']);self.assertEqual(self.refs('Reference~"R[12]"'),[])
 def test_invalid_expressions_fail_closed(self):
  for q in ('Value=','(Value=10k','NOT','AND Value=10k','Value!10k','Unknown=1','is:banana','has:Unknown','Value="unclosed'):
   with self.subTest(q=q),self.assertRaises(ValueError):self.refs(q)
 def test_bounded_grammar(self):
  for q in ('a'*4097,'('*25+'R1'+')'*25,' '.join('R1' for _ in range(257)),'Reference~"'+'?'*257+'"'):
   with self.subTest(q=q[:25]),self.assertRaises(ValueError):self.refs(q)
 def test_search_no_workspace_mutation(self):
  before=self.ws._serialize();self.refs('is:error OR is:warning');self.assertEqual(before,self.ws._serialize())
 def test_check_severity_filter(self):
  self.edit('R1',{'MPN':''});self.assertIn('R1',self.refs('is:warning OR is:error'))
 def test_filters_roundtrip_undo(self):
  before=self.ws._serialize();search.save_filter(self.ws,'R10k',{'query':'Value=10k','description':'Test'})
  payload=search.bundle(self.ws);self.assertEqual(payload['schema'],'wayricad-filters-1');self.ws.undo();self.assertEqual(before,self.ws._serialize())
  search.import_filters(self.ws,payload);self.ws.save();other=Workspace(Project(self.path));self.assertIn('R10k',other.state['saved_filters'])
 def test_filter_conflicts_require_replace(self):
  search.save_filter(self.ws,'X',{'query':'Value=10k'});bundle={'schema':'wayricad-filters-1','filters':{'X':{'query':'Value=1k'}}}
  with self.assertRaises(ValueError):search.import_filters(self.ws,bundle)
  search.import_filters(self.ws,bundle,True);self.assertEqual(self.ws.state['saved_filters']['X']['query'],'Value=1k')
 def test_filter_validation(self):
  for filters in ({'__proto__':{'query':'R1'}},{'X':{'query':'R1','execute':'x'}},{'X':{'query':'('}},{'X':{'query':'R1','case_sensitive':'false'}}):
   with self.subTest(filters=filters),self.assertRaises(ValueError):search.validate_filters(filters)

class BulkRecipeTests(Fixture):
 def recipe(self,ops,query='Reference=R1'):return {'schema':'wayricad-bulk-recipe-1','query':query,'operations':ops}
 def stage(self,recipe,variant=BASE,loss=False):
  p=actions.preview(self.ws,variant,recipe);return actions.apply(self.ws,variant,recipe,p['fingerprint'],'EDIT',loss)
 def test_multistep_literal_transform(self):
  self.edit('R1',{'Note':'  aBc  '});r=self.recipe([{'op':'trim','field':'Note'},{'op':'upper','field':'Note'},{'op':'replace','field':'Note','find':'B','value':'-'},{'op':'prefix','field':'Note','value':'['},{'op':'suffix','field':'Note','value':']'}]);self.stage(r);self.assertEqual(self.row('R1')['raw']['Note'],'[A-C]')
 def test_copy_and_fill(self):
  self.edit('R1',{'Note':'one'});self.stage(self.recipe([{'op':'copy','field':'Copied','source':'Note'},{'op':'fill_empty','field':'Note','value':'two'},{'op':'fill_empty','field':'Empty','value':'filled'}]));self.assertEqual(self.row('R1')['raw']['Copied'],'one');self.assertEqual(self.row('R1')['raw']['Note'],'one')
 def test_fill_skips_existing_all_noop(self):
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,self.recipe([{'op':'fill_empty','field':'Value','value':'x'}]))
 def test_clear_keeps_field(self):
  self.stage(self.recipe([{'op':'clear','field':'MPN'}]));self.assertIn('MPN',self.row('R1')['raw']);self.assertEqual(self.row('R1')['raw']['MPN'],'')
 def test_scope_requires_explicit_all(self):
  r=self.recipe([{'op':'set','field':'Note','value':'x'}],query='')
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,r)
  r['allow_all']=True;self.assertEqual(actions.preview(self.ws,BASE,r)['matched'],11)
 def test_scope_no_matches_not_success(self):
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,self.recipe([{'op':'set','field':'Value','value':'x'}],'Reference=R999'))
 def test_ids_must_be_valid_unique(self):
  for ids in (['bad'],[self.row('R1')['id']]*2,[],[False]):
   with self.subTest(ids=ids),self.assertRaises(ValueError):actions.preview(self.ws,BASE,{'ids':ids,'operations':[{'op':'set','field':'Value','value':'x'}]})
 def test_stale_review_refused(self):
  r=self.recipe([{'op':'set','field':'Value','value':'22k'}]);p=actions.preview(self.ws,BASE,r);self.edit('R2',{'Value':'11k'})
  with self.assertRaises(ValueError):actions.apply(self.ws,BASE,r,p['fingerprint'],'EDIT')
 def test_changed_recipe_refused(self):
  r=self.recipe([{'op':'set','field':'Value','value':'22k'}]);p=actions.preview(self.ws,BASE,r);r['operations'][0]['value']='33k'
  with self.assertRaises(ValueError):actions.apply(self.ws,BASE,r,p['fingerprint'],'EDIT')
 def test_variable_loss_confirmation(self):
  self.ws.set_variables('project',{'X':'10k'},BASE);self.edit('R1',{'Value':'${X}'})
  r=self.recipe([{'op':'set','field':'Value','value':'22k'}]);p=actions.preview(self.ws,BASE,r);self.assertGreater(p['variable_losses'],0)
  with self.assertRaises(ValueError):actions.apply(self.ws,BASE,r,p['fingerprint'],'EDIT',False)
  actions.apply(self.ws,BASE,r,p['fingerprint'],'EDIT',True);self.assertEqual(self.row('R1')['raw']['Value'],'22k')
 def test_confirmation_and_readonly_fields(self):
  r=self.recipe([{'op':'set','field':'Value','value':'22k'}]);p=actions.preview(self.ws,BASE,r)
  with self.assertRaises(ValueError):actions.apply(self.ws,BASE,r,p['fingerprint'],'YES')
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,self.recipe([{'op':'set','field':'Reference','value':'R9'}]))
 def test_shared_sheet_effects_in_review(self):
  r=self.recipe([{'op':'set','field':'Value','value':'77k'}],'Reference=R101');p=actions.preview(self.ws,BASE,r)
  self.assertTrue(any(e['reference']=='R201' for e in p['events']));self.assertEqual(self.row('R101')['fields']['Value'],'1k')
 def test_descendant_variant_review(self):
  self.ws.new_variant('Child','Economy');self.ws.new_variant('Grandchild','Child')
  r=self.recipe([{'op':'set','field':'Note','value':'child'}]);p=actions.preview(self.ws,'Economy',r)
  self.assertEqual({e['variant'] for e in p['events']},{'Economy','Child','Grandchild'})
  actions.apply(self.ws,'Economy',r,p['fingerprint'],'EDIT');self.assertEqual(self.row('R1','Grandchild')['fields']['Note'],'child')
 def test_one_undo_restores_transaction(self):
  before=self.ws._serialize();self.stage(self.recipe([{'op':'set','field':'Note','value':'x'},{'op':'set','field':'Value','value':'22k'}],'Reference~"R?"'));self.ws.undo();self.assertEqual(before,self.ws._serialize())
 def test_native_files_untouched(self):
  self.stage(self.recipe([{'op':'set','field':'Value','value':'22k'}]));self.ws.save();self.ws.project.check_unchanged()
 def test_invalid_operations(self):
  for ops in ([{'op':'exec','field':'Value'}],[{'op':'replace','field':'Value','find':'','value':'x'}],[{'op':'copy','field':'Value'}],[{'op':'set','field':'Value','value':5}],[],[{'op':'set','field':'Value','value':'x'}]*31):
   with self.subTest(ops=ops[:1]),self.assertRaises(ValueError):actions.preview(self.ws,BASE,self.recipe(ops))

class ConfigurationTests(Fixture):
 def test_multioperation_plan_commit_undo(self):
  ops=[{'op':'variant-add','name':'NewVariant'},{'op':'filter-save','name':'Resistors','record':{'query':'Reference~"R*"'}}];before=self.ws._serialize();p=configedit.preview(self.ws,ops);self.assertEqual(before,self.ws._serialize());configedit.apply(self.ws,ops,p['fingerprint'],'CONFIG');self.assertIn('NewVariant',self.ws.state['variants']);self.ws.undo();self.assertEqual(before,self.ws._serialize())
 def test_variables_acknowledgement(self):
  ops=[{'op':'variables','scope':'project','values':{'REV':'B'}}];p=configedit.preview(self.ws,ops);self.assertTrue(p['acknowledgement_required'])
  with self.assertRaises(ValueError):configedit.apply(self.ws,ops,p['fingerprint'],'CONFIG')
  configedit.apply(self.ws,ops,p['fingerprint'],'CONFIG',True);self.assertEqual(self.ws.variables(BASE)['REV'],'B')
 def test_unknown_and_partial_config_no_commit(self):
  before=self.ws._serialize();ops=[{'op':'variant-add','name':'Temp'},{'op':'arbitrary','value':'bad'}]
  with self.assertRaises(ValueError):configedit.preview(self.ws,ops)
  self.assertEqual(before,self.ws._serialize())

class PipelineTests(Fixture):
 def config(self):return dict(automation.default_pipeline(),variants=[BASE],formats=['csv','json'],reports=['checks'])
 def test_success_integrity_no_mutation(self):
  before=self.ws._serialize();r=automation.pipeline(self.ws,self.config(),self.dir/'release');self.assertEqual(r['status'],'PASSED');self.assertTrue(automation.verify_run(self.dir/'release')['valid']);self.assertEqual(before,self.ws._serialize());self.ws.project.check_unchanged()
 def test_no_overwrite(self):
  dest=self.dir/'release';dest.mkdir();(dest/'keep').write_text('preserve')
  with self.assertRaises(FileExistsError):automation.pipeline(self.ws,self.config(),dest)
  self.assertEqual((dest/'keep').read_text(),'preserve')
 def test_failure_publishes_reports_not_bom(self):
  c=self.config();c['policy']={'checks':'error','health':'unknown'};r=automation.pipeline(self.ws,c,self.dir/'failed');self.assertEqual(r['status'],'FAILED');m=json.loads((self.dir/'failed/manifest.json').read_text());self.assertTrue(m['gates']);self.assertTrue(all(Path(x).name in ('checks.json','health.json','workspace_snapshot.json') for x in m['files']));self.assertTrue(automation.verify_run(self.dir/'failed')['valid'])
 def test_stock_policy_unknown_fails(self):
  c=self.config();c['policy']={'checks':'error','require_stock':True};r=automation.pipeline(self.ws,c,self.dir/'unknown');self.assertEqual(r['status'],'FAILED');self.assertTrue(any(x['kind']=='stock_not_observed_covered' for x in r['gates']))
 def test_tamper_and_extra_detection(self):
  dest=self.dir/'release';automation.pipeline(self.ws,self.config(),dest);target=next(dest.rglob('*.csv'));target.write_text('changed');(dest/'001/manifest.json').write_text('{}');r=automation.verify_run(dest);self.assertFalse(r['valid']);self.assertTrue(r['changed_or_missing']);self.assertIn('001/manifest.json',r['unlisted'])
 def test_manifest_path_escape_rejected(self):
  dest=self.dir/'bad';dest.mkdir();(dest/'manifest.json').write_text(json.dumps({'schema':'wayricad-run-1','files':{'../outside':{'bytes':0,'sha256':'x'}}}))
  with self.assertRaises(ValueError):automation.verify_run(dest)
 def test_fail_closed_invalid_pipeline(self):
  for changes in ({'formats':['zip']},{'variants':['Unknown']},{'policy':{'checks':'none'}},{'execute':'rm'},{'name':'../out'},{'policy':{'require_stock':'true'}}):
   with self.subTest(changes=changes),self.assertRaises(ValueError):automation.validate_pipeline(dict(self.config(),**changes),self.ws)
 def test_all_export_formats_in_pipeline(self):
  c=self.config();c['formats']=[f for f in automation.MIME if f!='zip'];r=automation.pipeline(self.ws,c,self.dir/'all');self.assertEqual(r['status'],'PASSED');self.assertEqual(len(list((self.dir/'all/001').iterdir())),12)
 def test_source_change_block(self):
  self.ws.project.root.write_text(self.ws.project.root.read_text()+'\n')
  with self.assertRaises(ValueError):automation.pipeline(self.ws,self.config(),self.dir/'drift')
 def test_json_duplicate_unsafe_nonfinite(self):
  for text in ('{"a":1,"a":2}','{"__proto__":1}','{"x":NaN}','{"x":Infinity}'):
   with self.subTest(text=text),self.assertRaises(ValueError):automation.strict_loads(text)
 def test_output_path_guards(self):
  for name in ('out.kicad_sch','out.kicad_pro','Board.wayricad-bom.json','missing/report.json'):
   with self.subTest(name=name),self.assertRaises((ValueError,OSError)):automation.write_new(self.dir/name,b'bad')
 def test_jobset_schema_and_quoting(self):
  fs=automation.jobset_files(self.ws,self.dir/'job folder',config=self.config());j=json.loads(fs['WayriCAD_BOM.kicad_jobset']);self.assertEqual(j['meta']['version'],1);job=j['jobs'][0];self.assertEqual(job['type'],'special_execute');self.assertFalse(job['settings']['ignore_exit_code']);self.assertTrue(job['settings']['record_output']);self.assertEqual(j['outputs'][0]['only'],[job['id']]);self.assertIn('"' if os.name=='nt' else "'",job['settings']['command'])
 def test_windows_shell_rejects_expansion(self):
  for path in ('C:\\%USER%\\python.exe','C:\\bang!\\python.exe','C:\\bad"\\p.exe'):
   with self.subTest(path=path),self.assertRaises(ValueError):automation.shell_command([path,'runner.py'],'windows')
  self.assertEqual(automation.shell_command(['C:\\A & B\\python.exe','x.py'],'windows'),'"C:\\A & B\\python.exe" "x.py"')
 def test_job_runner_with_simulated_kicad_environment(self):
  d=self.dir/'jobs';d.mkdir();fs=automation.jobset_files(self.ws,d,config=self.config())
  for n,data in fs.items():(d/n).write_bytes(data)
  temp=self.dir/'ki-job-output';temp.mkdir();env=dict(os.environ,JOBSET_OUTPUT_WORK_PATH=str(temp));p=subprocess.run([sys.executable,str(d/'run_wayricad_job.py')],capture_output=True,text=True,env=env,timeout=30);self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(automation.verify_run(temp/'WayriCAD_BOM')['valid'])
 def test_job_runner_no_env_manual_new_folders(self):
  d=self.dir/'jobs';d.mkdir()
  for n,data in automation.jobset_files(self.ws,d,config=self.config()).items():(d/n).write_bytes(data)
  env=dict(os.environ);env.pop('JOBSET_OUTPUT_WORK_PATH',None)
  p=subprocess.run([sys.executable,str(d/'run_wayricad_job.py')],capture_output=True,text=True,env=env,timeout=30);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(len(list(d.glob('run-*'))),1)
 def test_jobset_zip(self):
  data,_,_=automation.jobset_bundle(self.ws,self.dir/'jobs',config=self.config());z=zipfile.ZipFile(io.BytesIO(data));self.assertIsNone(z.testzip());self.assertEqual(len(z.namelist()),5)
 def test_jobset_requires_absolute_destination(self):
  for name in ('','relative'):
   with self.subTest(name=name),self.assertRaises(ValueError):automation.jobset_files(self.ws,name)

class CLITests(Fixture):
 def call(self,*args):
  stdout=io.StringIO();stderr=io.StringIO()
  with redirect_stdout(stdout),redirect_stderr(stderr):code=cli.main([str(x) for x in args])
  return code,stdout.getvalue(),stderr.getvalue()
 def test_doctor_without_project(self):
  code,out,err=self.call('doctor');self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['schema'],'wayricad-cli-1')
 def test_schema_command(self):
  code,out,err=self.call('schema');self.assertEqual(code,0);self.assertIn('jobset',json.loads(out)['data']['commands'])
 def test_query_pagination_grouping(self):
  code,out,err=self.call('query',self.path,'--query','Value=10k','--rows','--limit','2','--group-by','Value');self.assertEqual(code,0,err);r=json.loads(out)['data'];self.assertEqual(r['matched'],3);self.assertEqual(r['returned'],2);self.assertEqual(r['next_offset'],2);self.assertEqual(r['group_count'],1)
 def test_readonly_command_suite(self):
  before={f.name:sha(f.read_bytes()) for f in self.dir.iterdir()}
  for args in (('info',),('list','--what','fields'),('check',),('health',),('analyze',),('compare','--right','Economy'),('templates',)):
   code,out,err=self.call(args[0],self.path,*args[1:]);self.assertEqual(code,0,(args,err));self.assertEqual(json.loads(out)['schema'],'wayricad-cli-1')
  self.assertEqual(before,{f.name:sha(f.read_bytes()) for f in self.dir.iterdir()})
 def test_report_exclusive_write(self):
  target=self.dir/'report.json';code,_,err=self.call('info',self.path,'--output',target);self.assertEqual(code,0,err);before=target.read_bytes();self.assertEqual(self.call('info',self.path,'--output',target)[0],4);self.assertEqual(target.read_bytes(),before)
 def test_bulk_cross_process_preview_apply_native_unchanged(self):
  recipe=self.dir/'recipe.json';recipe.write_text(json.dumps({'query':'Reference=R1','operations':[{'op':'set','field':'Value','value':'22k'}]}));plan=self.dir/'plan.json';code,_,err=self.call('bulk','preview',self.path,'--recipe',recipe,'--output',plan);self.assertEqual(code,0,err)
  code,out,err=self.call('bulk','apply',self.path,'--plan',plan,'--confirm','EDIT');self.assertEqual(code,0,err);other=Workspace(Project(self.path));self.assertEqual(next(r for r in other.rows() if r['ref']=='R1')['fields']['Value'],'22k');self.ws.project.check_unchanged()
 def test_bulk_invalid_report_does_not_save(self):
  recipe=self.dir/'recipe.json';recipe.write_text(json.dumps({'query':'Reference=R1','operations':[{'op':'set','field':'Value','value':'22k'}]}));plan=self.dir/'plan.json';self.call('bulk','preview',self.path,'--recipe',recipe,'--output',plan)
  code,_,_=self.call('bulk','apply',self.path,'--plan',plan,'--confirm','EDIT','--output',self.dir/'report.kicad_pro');self.assertEqual(code,2);self.assertFalse(self.ws.sidecar.exists())
 def test_config_roundtrip(self):
  changes=self.dir/'changes.json';changes.write_text(json.dumps([{'op':'variant-add','name':'CLI Variant'}]));plan=self.dir/'config.json';code,_,err=self.call('config','preview',self.path,'--changes',changes,'--output',plan);self.assertEqual(code,0,err);code,_,err=self.call('config','apply',self.path,'--plan',plan,'--confirm','CONFIG');self.assertEqual(code,0,err);self.assertIn('CLI Variant',Workspace(Project(self.path)).state['variants'])
 def test_stale_plan_exit_five(self):
  changes=self.dir/'changes.json';changes.write_text(json.dumps([{'op':'variant-add','name':'CLI Variant'}]));plan=self.dir/'config.json';self.call('config','preview',self.path,'--changes',changes,'--output',plan);self.edit('R1',{'Value':'22k'});self.ws.save();code,_,err=self.call('config','apply',self.path,'--plan',plan,'--confirm','CONFIG');self.assertEqual(code,5,err)
 def test_health_policy_exit_three(self):self.assertEqual(self.call('health',self.path,'--fail-on','unknown')[0],3)
 def test_missing_input_exit_four(self):self.assertEqual(self.call('info',self.dir/'missing.kicad_pro')[0],4)
 def test_bad_query_exit_two_json_error(self):
  code,out,err=self.call('query',self.path,'--query','Value=');self.assertEqual(code,2);self.assertEqual(out,'');self.assertEqual(json.loads(err)['schema'],'wayricad-cli-error-1')
 def test_all_cli_exports(self):
  for fmt in automation.MIME:
   args=('release',self.path,'--template','Purchasing','--output',self.dir/'release.zip') if fmt=='zip' else ('export',self.path,'--template','Purchasing','--format',fmt,'--output',self.dir/('bom.'+fmt))
   code,_,err=self.call(*args);self.assertEqual(code,0,(fmt,err))
 def test_native_preview_and_apply_separate(self):
  self.edit('R1',{'Value':'22k'});self.ws.save();plan=self.dir/'native.json';code,_,err=self.call('native','preview',self.path,'--output',plan);self.assertEqual(code,0,err)
  code,_,err=self.call('native','apply',self.path,'--plan',plan,'--confirm','APPLY');self.assertNotEqual(code,0);self.ws.project.check_unchanged()
  code,_,err=self.call('native','apply',self.path,'--plan',plan,'--confirm','APPLY','--editors-closed');self.assertEqual(code,0,err);self.assertEqual(next(r for r in Workspace(Project(self.path)).rows() if r['ref']=='R1')['fields']['Value'],'22k')

# Structurally modeled driver objects. This is not an installed KiCad API server.
class FakeBoard:
 def __init__(self,project):
  self.document=NS(project=NS(name=project.name,path=str(project.pro_path.parent)),board_filename=project.name+'.kicad_pcb');self.selection=[];self.footprints=[];self.calls=[];self.fail_add=False
  for c in project.components:
   m=c.members[0];pad=NS(id=str(uuid.uuid4()));field=NS(text=NS(id=str(uuid.uuid4()),value=c.ref));fp=NS(id=str(uuid.uuid4()),sheet_path=NS(path=[NS(value=x) for x in (m.path+'/'+m.uuid).strip('/').split('/')]),reference_field=field,value_field=NS(text=NS(id=str(uuid.uuid4()),value='')),definition=NS(items=[pad]),attributes=NS(not_in_schematic=False),texts_and_fields=[])
   self.footprints.append(fp)
 def get_footprints(self):return self.footprints
 def get_selection(self):return self.selection
 def clear_selection(self):self.calls.append(('clear',threading.get_ident()));self.selection=[]
 def add_to_selection(self,items):
  self.calls.append(('select',threading.get_ident()))
  if self.fail_add:self.fail_add=False;raise RuntimeError('fixture selection failure')
  self.selection.extend(items)
class FakeClient:
 def __init__(self,board,major=10):self.board=board;self.major=major;self.actions=[];self.closed=False
 def get_version(self):return NS(major=self.major,minor=0,patch=0,full_version=f'{self.major}.0.0-fixture')
 def get_board(self):return self.board
 def run_action(self,name):self.actions.append(name);return 1
 def close(self):self.closed=True
class BridgeTests(Fixture):
 def setUp(self):super().setUp();self.board=FakeBoard(self.ws.project);self.client=FakeClient(self.board);self.bridge=Bridge(lambda **kwargs:self.client)
 def tearDown(self):self.bridge.close();super().tearDown()
 def test_full_uuid_mapping(self):
  r=self.bridge.connect(self.ws.project);self.assertEqual(r['mapped_components'],11);self.assertFalse(r['native_data_modified']);self.assertEqual(r['schematic'],'native-relay-unverified')
 def test_bom_to_board_readback(self):
  self.bridge.connect(self.ws.project);ids=[self.row('R1')['id'],self.row('R2')['id']];r=self.bridge.select(ids);self.assertEqual(set(r['ids']),set(ids));self.assertEqual(len(self.board.selection),2);self.ws.project.check_unchanged()
 def test_editor_pad_and_field_to_component(self):
  self.bridge.connect(self.ws.project);fp=self.bridge.mapping[self.row('R1')['id']];self.board.selection=[fp.definition.items[0],fp.reference_field];r=self.bridge.poll();self.assertEqual(r['references'],['R1']);self.assertEqual(r['unmapped_selected'],0)
 def test_empty_and_unmapped_selection(self):
  self.bridge.connect(self.ws.project);self.board.selection=[NS(id=str(uuid.uuid4()))];r=self.bridge.poll();self.assertEqual(r['ids'],[]);self.assertEqual(r['unmapped_selected'],1);self.board.selection=[];self.assertEqual(self.bridge.poll()['unmapped_selected'],0)
 def test_repeated_sheet_instance_mapping(self):
  self.bridge.connect(self.ws.project);a=self.bridge.mapping[self.row('R101')['id']];b=self.bridge.mapping[self.row('R201')['id']];self.assertNotEqual(a.id,b.id)
 def test_wrong_project_refused(self):
  self.board.document.project.name='Other';
  with self.assertRaises(BridgeUnavailable):self.bridge.connect(self.ws.project)
  self.assertFalse(self.bridge.poll()['connected'])
 def test_active_board_switch_disconnects(self):
  self.bridge.connect(self.ws.project);self.board.document.board_filename='other.kicad_pcb'
  with self.assertRaises(BridgeUnavailable):self.bridge.poll()
  self.assertFalse(self.bridge.poll()['connected'])
 def test_reference_fallback_opt_in(self):
  fp=self.board.footprints[0];fp.sheet_path=NS(path=[]);r=self.bridge.connect(self.ws.project);self.assertEqual(r['mapped_components'],10);r=self.bridge.connect(self.ws.project,{'reference_fallback':True});self.assertEqual(r['mapped_components'],11);self.assertTrue(any('weak reference' in w for w in r['warnings']))
 def test_reference_does_not_override_mismatched_uuid(self):
  self.board.footprints[0].sheet_path=NS(path=[NS(value=str(uuid.uuid4()))]);r=self.bridge.connect(self.ws.project,{'reference_fallback':True});self.assertEqual(r['mapped_components'],10)
 def test_duplicate_paths_refused(self):
  extra=deepcopy(self.board.footprints[0]);extra.id=str(uuid.uuid4());self.board.footprints.append(extra);r=self.bridge.connect(self.ws.project);self.assertEqual(r['mapped_components'],10);self.assertTrue(any('duplicate' in w for w in r['warnings']))
 def test_missing_mapping_no_partial_clear(self):
  missing=self.ws.project.components[0].id;self.board.footprints.pop(0);self.bridge.connect(self.ws.project);self.board.selection=[self.board.footprints[0]];old=list(self.board.selection)
  with self.assertRaises(ValueError):self.bridge.select([missing,self.ws.project.components[1].id])
  self.assertEqual(self.board.selection,old)
 def test_failed_selection_restores_old(self):
  self.bridge.connect(self.ws.project);self.board.selection=[self.board.footprints[0]];old=list(self.board.selection);self.board.fail_add=True
  with self.assertRaises(BridgeUnavailable):self.bridge.select([self.row('R1')['id']])
  self.assertEqual(self.board.selection,old)
 def test_zoom_opt_in_and_allowlist(self):
  self.bridge.connect(self.ws.project);r=self.bridge.select([self.row('R1')['id']],focus=True);self.assertEqual(r['focus_result'],'disabled_enable_experimental_focus');self.assertEqual(self.client.actions,[])
  self.bridge.connect(self.ws.project,{'experimental_focus':True});r=self.bridge.select([self.row('R1')['id']],focus=True);self.assertEqual(r['focus_result'],'submitted_unverified');self.assertEqual(self.client.actions,['common.Control.zoomFitSelection'])
 def test_source_drift_prevents_selection(self):
  self.bridge.connect(self.ws.project);self.ws.project.root.write_text(self.ws.project.root.read_text()+'\n')
  with self.assertRaises(ValueError):self.bridge.select([self.row('R1')['id']])
  self.assertEqual(self.board.calls,[])
 def test_future_host_requires_explicit_optin(self):
  self.client.major=11
  with self.assertRaises(BridgeUnavailable):self.bridge.connect(self.ws.project)
  self.assertTrue(self.bridge.connect(self.ws.project,{'allow_untested':True})['connected'])
 def test_no_remote_socket(self):
  with self.assertRaises(ValueError):self.bridge.connect(self.ws.project,{'socket':'tcp://host:1'})
 def test_single_thread_service(self):
  service=SelectionService(lambda **kwargs:self.client)
  try:
   service.call('connect',self.ws.project);service.call('select',[self.row('R1')['id']]);service.call('poll');self.assertEqual(len({x[1] for x in self.board.calls}),1);self.assertNotEqual(self.board.calls[0][1],threading.get_ident())
  finally:service.close()
 def test_discovery_inherited_context_only(self):
  with patch.dict(os.environ,{'KICAD_API_SOCKET':'fixture-local'}):r=self.bridge.discover();self.assertEqual(r['project'],str(self.path));self.assertFalse(self.bridge.poll()['connected'])
 def test_dot_in_project_name_preserved(self):
  self.board.document.project.name='Board.rev.B';p,_=document_identity(self.board);self.assertTrue(p.endswith('Board.rev.B.kicad_pro'))


class V4EdgeTests(Fixture):
 def test_bulk_boolean_text_and_clear_guard(self):
  recipe={'query':'Reference=R1','operations':[{'op':'set','field':'InBOM','value':'false'}]};p=actions.preview(self.ws,BASE,recipe);actions.apply(self.ws,BASE,recipe,p['fingerprint'],'EDIT');self.assertFalse(self.row('R1')['flags']['in_bom'])
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,{'query':'Reference=R1','operations':[{'op':'clear','field':'InBOM'}]})
 def test_bulk_aliases_ordered(self):
  self.edit('R1',{'Manufacturer Part Number':'OLD','MPN':''});r=self.row('R1');source=r['field_name_sources']['MPN'];recipe={'query':'Reference=R1','operations':[{'op':'set','field':'MPN','value':'NEW'},{'op':'suffix','field':source,'value':'-SUFFIX'}]};p=actions.preview(self.ws,BASE,recipe);actions.apply(self.ws,BASE,recipe,p['fingerprint'],'EDIT');self.assertEqual(self.row('R1')['fields']['MPN'],'NEW-SUFFIX')
 def test_bulk_reset_then_transform_rejected(self):
  self.edit('R1',{'Value':'22k'});recipe={'query':'Reference=R1','operations':[{'op':'reset_to_base','field':'Value'},{'op':'suffix','field':'Value','value':'-bad'}]}
  with self.assertRaises(ValueError):actions.preview(self.ws,BASE,recipe)
 def test_cli_no_abbreviations_and_usage_json(self):
  for args in (['info',str(self.path),'--out','out.json'],[],['query',str(self.path),'--case-sens']):
   out=io.StringIO();err=io.StringIO()
   with redirect_stdout(out),redirect_stderr(err):code=cli.main(args)
   self.assertEqual(code,2);self.assertEqual(json.loads(err.getvalue())['schema'],'wayricad-cli-error-1')
 def test_cli_gui_detached_and_quit(self):
  import http.client
  from urllib.parse import urlsplit
  from bomstudio.launch import detached
  result=detached(str(self.path),no_browser=True,no_auto_link=True);u=urlsplit(result['url']);token=u.fragment.removeprefix('token=')
  try:
   c=http.client.HTTPConnection(u.hostname,u.port,timeout=5);c.request('GET','/api/state',headers={'X-Bom-Token':token});resp=c.getresponse();self.assertEqual(resp.status,200);self.assertEqual(json.loads(resp.read())['project']['components'],11);c.close()
  finally:
   c=http.client.HTTPConnection(u.hostname,u.port,timeout=5);c.request('POST','/api/quit',body='{}',headers={'X-Bom-Token':token,'Content-Type':'application/json'});resp=c.getresponse();resp.read();c.close()
   from bomstudio.launch import _children
   import time
   deadline=time.monotonic()+5
   while result['pid'] in _children and time.monotonic()<deadline:time.sleep(.05)
   self.assertNotIn(result['pid'],_children)
   shutil.rmtree(result['session_directory'],ignore_errors=True)
 def test_cli_evidence_review_apply(self):
  payload=self.dir/'evidence.json';payload.write_text(json.dumps({'format':'manual','record':{'manufacturer':'Demo Components','mpn':'DEMO-R0603-10K','source_url':'https://example.org/fixture','notes':'Synthetic evidence'}}));plan=self.dir/'evidence-plan.json'
  for args in (['evidence','preview',str(self.path),'--payload',str(payload),'--output',str(plan)],['evidence','apply',str(self.path),'--plan',str(plan),'--confirm','IMPORT','--reviewed']):
   err=io.StringIO()
   with redirect_stdout(io.StringIO()),redirect_stderr(err):code=cli.main(args)
   self.assertEqual(code,0,err.getvalue())
  self.assertEqual(len(Workspace(Project(self.path)).state['evidence']),1)
 def test_pipeline_snapshot_hash_matches_manifest(self):
  c=dict(automation.default_pipeline(),variants=[BASE],formats=['json'],reports=['checks']);dest=self.dir/'release';automation.pipeline(self.ws,c,dest);m=json.loads((dest/'manifest.json').read_text());self.assertEqual(sha((dest/'workspace_snapshot.json').read_bytes()),m['workspace_sha256'])
 def test_auto_discovery_in_application_injected(self):
  from bomstudio.server import Application
  board=FakeBoard(self.ws.project);client=FakeClient(board)
  with patch.dict(os.environ,{'KICAD_API_SOCKET':'fixture-local'}),patch('bomstudio.bridge.SelectionService',side_effect=lambda:SelectionService(lambda **kwargs:client)):
   app=Application(auto_link=True)
  try:self.assertEqual(app.workspace.project.pro_path,self.path);self.assertTrue(app.link.call('poll')['connected']);self.assertIn('discovered',app.state()['startup_note'])
  finally:app.link.close()

 def test_deleted_starter_template_stays_deleted_after_reload(self):
  from bomstudio import catalog
  catalog.manage(self.ws,'templates','delete','Generic ERP CSV')
  self.ws.save()
  reopened=Workspace(Project(self.path))
  self.assertNotIn('Generic ERP CSV',reopened.state['templates'])

 def test_cli_unknown_command_is_usage_error(self):
  out=io.StringIO();err=io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main(['qeury',str(self.path)])
  self.assertEqual(code,2);self.assertEqual(json.loads(err.getvalue())['schema'],'wayricad-cli-error-1')
 def test_shipped_automation_examples_validate(self):
  from bomstudio import configedit,search
  folder=Path(__file__).resolve().parents[1]/'examples/automation'
  for name in ('pipeline-default.json','pipeline-strict.json'):automation.validate_pipeline(json.loads((folder/name).read_text()),self.ws)
  for name in ('bulk-standardize-value.json','bulk-review-notes.json'):self.assertGreater(actions.preview(self.ws,BASE,json.loads((folder/name).read_text()))['matched'],0)
  configedit.preview(self.ws,json.loads((folder/'config-create-variant.json').read_text()))
  search.validate_filters(json.loads((folder/'filters.wayricad-filters.json').read_text())['filters'])

if __name__=='__main__':unittest.main()
