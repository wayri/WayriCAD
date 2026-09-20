"""Assembly handoff integration. Local format contracts, not portal certification."""
from copy import deepcopy
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
import csv,io,json,zipfile,unittest,threading,http.client,shutil
import xml.etree.ElementTree as ET
from unittest.mock import patch
from test_core import Fixture
from bomstudio import assembler_export as ae,automation,cli,nativefirst
from bomstudio.native import BASE,Project,sha
from bomstudio.engine import Workspace
from bomstudio.server import Application,Server

class AssemblyConfigTests(unittest.TestCase):
 def test_all_requested_providers_present(self):self.assertTrue({'jlcpcb','pcbway','hqpcb','nextpcb','sierra','pcbpower'}<=set(ae.PROFILES))
 def test_new_recipient_handoffs_require_review(self):
  for name in ('aisler','pcprocess','krypton'):
   p=ae.profiles()[name];self.assertEqual(p['status'],'review_required');self.assertFalse(p['portal_tested']);self.assertEqual(p['headers'],ae.PROFILES['generic']['headers'])
 def test_no_hq_next_alias(self):self.assertNotEqual(ae.PROFILES['hqpcb'],ae.PROFILES['nextpcb'])
 def test_jlc_four_columns_no_fake_quantity(self):self.assertEqual(ae.PROFILES['jlcpcb']['headers'],['Comment','Designator','Footprint','LCSC Part #'])
 def test_documentation_status_not_certified(self):self.assertTrue(all(not p['portal_tested'] for p in ae.profiles().values()))
 def test_required_pcb_power_fields(self):self.assertTrue({'MPN','Quantity','Reference Designator','Manufacturer Name'}<=set(ae.PROFILES['pcbpower']['headers']))
 def test_default_copies(self):a=ae.validate_config();a['fields']['value']='x';self.assertEqual(ae.validate_config()['fields']['value'],'Value')
 def test_bad_inputs(self):
  for c in [[],{'boards':2},{'attrition':5},{'profiles':[]},{'profiles':['other']},{'profiles':['jlcpcb','jlcpcb']},{'formats':[]},{'formats':['xls']},{'fields':{'bad':'x'}},{'fields':{'mpn':3}},{'footprint_mode':'guess'},{'acknowledge_review_required':'yes'},{'sku_fields':{'other':'x'}}]:
   with self.subTest(c=c),self.assertRaises(ValueError):ae.validate_config(c)
 def test_cannot_remove_reference(self):
  with self.assertRaises(ValueError):ae.validate_config({'profile_overrides':{'jlcpcb':{'keys':['comment','footprint'],'headers':['Comment','Footprint']}}})
 def test_cannot_remove_quantity(self):
  with self.assertRaises(ValueError):ae.validate_config({'profile_overrides':{'generic':{'keys':['references','mpn','footprint'],'headers':['Refs','MPN','Footprint']}}})
 def test_cannot_remove_required_manufacturer(self):
  p=deepcopy(ae.PROFILES['pcbpower']);i=p['keys'].index('manufacturer');p['keys'].pop(i);p['headers'].pop(i)
  with self.assertRaises(ValueError):ae.validate_config({'profile_overrides':{'pcbpower':{'keys':p['keys'],'headers':p['headers']}}})
 def test_required_sku_not_hidden(self):
  with self.assertRaises(ValueError):ae.validate_config({'require_supplier_code':True,'profile_overrides':{'jlcpcb':{'keys':['comment','references','footprint'],'headers':['Comment','Designator','Footprint']}}})
 def test_custom_headings_need_review(self):p=ae.profiles({'profile_overrides':{'jlcpcb':{'headers':['Value','Refs','Package','Code']}}});self.assertEqual(p['jlcpcb']['status'],'custom_review_required')
 def test_formula_header_rejected(self):
  with self.assertRaises(ValueError):ae.validate_config({'profile_overrides':{'jlcpcb':{'headers':['=1','Refs','Package','Code']}}})
 def test_duplicate_header_rejected(self):
  with self.assertRaises(ValueError):ae.validate_config({'profile_overrides':{'jlcpcb':{'headers':['X','X','Y','Z']}}})

class AssemblyTests(Fixture):
 def report(self,**c):return ae.preview(self.ws,BASE,c)
 def line(self,ref,r=None):return next(l for l in (r or self.report())['profiles'][0]['lines'] if ref in l['reference_list'])
 def all_config(self):return {'profiles':list(ae.PROFILES),'acknowledge_review_required':True}
 def test_counts_per_board(self):r=self.report();self.assertEqual(r['summary']['fitted_on_board_components'],10);self.assertEqual(r['profiles'][0]['quantity_per_board'],10);self.assertTrue(r['summary']['reconciled'])
 def test_all_profiles_reconcile(self):r=self.report(**self.all_config());self.assertEqual(r['status'],'READY_FOR_REVIEW');self.assertTrue(all(p['quantity_per_board']==10 for p in r['profiles']))
 def test_no_mutation_on_read_or_export(self):
  before=self.ws._serialize();sources={p:p.read_bytes() for p in self.ws.project.documents};ae.export(self.ws,config=self.all_config());self.assertEqual(self.ws._serialize(),before);self.assertEqual(nativefirst.preferences(self.ws)['mode'],'native');self.assertTrue(all(p.read_bytes()==b for p,b in sources.items()))
 def test_boards_attrition_moq_never_change_assembly_qty(self):
  self.ws.state['settings'].update(boards=100,attrition=50);self.ws.edit([r['id'] for r in self.ws.rows()],BASE,{'MOQ':'500','OrderMultiple':'100','Supplier':'Mouser'});r=self.report();self.assertEqual(r['profiles'][0]['quantity_per_board'],10);self.assertFalse(r['summary']['build_multiplier_applied'])
 def test_exclude_dnp(self):self.assertIn('R4',[r['reference'] for r in self.report()['excluded']])
 def test_exclude_bom(self):self.edit('R1',{'in_bom':False});self.assertEqual(self.report()['profiles'][0]['quantity_per_board'],9)
 def test_exclude_board(self):self.edit('R1',{'on_board':False});self.assertEqual(self.report()['profiles'][0]['quantity_per_board'],9)
 def test_position_file_flag_not_assembly_exclusion(self):self.edit('R1',{'in_pos_files':False});self.assertEqual(self.report()['profiles'][0]['quantity_per_board'],10)
 def test_named_variant_not_ignored(self):self.ws.new_variant('Alt',BASE);self.edit('R1',{'dnp':True},'Alt');r=ae.preview(self.ws,'Alt');self.assertEqual(r['profiles'][0]['quantity_per_board'],9)
 def test_references_explicit_and_counted(self):
  for l in self.report()['profiles'][0]['lines']:self.assertEqual(l['qty_per_board'],len(l['reference_list']));self.assertEqual(l['references'],', '.join(l['reference_list']))
 def test_full_description_not_value_when_available(self):self.edit('R1',{'Description':'Thin film precision resistor'});self.assertEqual(self.line('R1')['description'],'Thin film precision resistor')
 def test_comment_auto_falls_back_value(self):self.assertEqual(self.line('R1')['comment'],self.line('R1')['value'])
 def test_explicit_blank_is_authoritative(self):self.edit('R1',{'Assembly Description':''});r=self.report(profiles=['sierra'],fields={'description':'Assembly Description'});self.assertEqual(r['status'],'BLOCKED')
 def test_lcsc_code_not_distributor_sku(self):self.edit('R1',{'SupplierSKU':'123-ND','DigiKey Part Number':'123-ND','Mouser Part Number':'001-R'});self.assertEqual(self.line('R1')['sku'],'')
 def test_actual_lcsc_code(self):self.edit('R1',{'LCSC Part #':'C12345'});self.assertEqual(self.line('R1')['sku'],'C12345')
 def test_lcsc_wrong_code_blocks(self):self.edit('R1',{'LCSC Part #':'123-ND'});self.assertEqual(self.report()['status'],'BLOCKED')
 def test_require_supplier_code(self):self.assertEqual(self.report(require_supplier_code=True)['status'],'BLOCKED')
 def test_mpn_not_guessed(self):self.edit('R1',{'MPN':''});self.assertEqual(self.report(profiles=['pcbpower'])['status'],'BLOCKED')
 def test_footprint_name_mode_keeps_source(self):
  full=self.line('R1')['original_footprint'];r=self.report(footprint_mode='name');self.assertEqual(self.line('R1',r)['footprint'],full.split(':',1)[1]);self.assertEqual(self.row('R1')['physical']['Footprint'],full)
 def test_same_sku_conflict_blocks(self):self.edit('R1',{'LCSC':'C1234'});self.edit('C1',{'LCSC':'C1234'});self.assertEqual(self.report()['status'],'BLOCKED')
 def test_unknown_profile_needs_ack(self):self.assertEqual(self.report(profiles=['hqpcb'])['status'],'REVIEW_REQUIRED')
 def test_acknowledgement_never_bypasses_missing_data(self):self.edit('R1',{'Footprint':''});self.assertEqual(self.report(**self.all_config())['status'],'BLOCKED')
 def test_rule_area_source_error_not_bypassed(self):
  checks=self.ws.checks()+[{'severity':'error','reference':'','code':'RULE','message':'Rule-area attributes need validation'}]
  with patch.object(self.ws,'checks',return_value=checks):self.assertEqual(self.report(**self.all_config())['status'],'BLOCKED')
 def test_case_duplicate_reference_blocked(self):
  rows=deepcopy(self.ws.rows());rows[1]['ref']=rows[0]['ref'].lower()
  with patch.object(self.ws,'rows',return_value=rows):self.assertEqual(self.report()['status'],'BLOCKED')
 def test_unannotated_reference_blocked(self):
  rows=deepcopy(self.ws.rows());rows[0]['ref']='R?'
  with patch.object(self.ws,'rows',return_value=rows):self.assertEqual(self.report()['status'],'BLOCKED')
 def test_same_value_different_part_not_pooled(self):self.edit('R1',{'MPN':'ORDERABLE-X'});self.edit('R2',{'Value':self.row('R1')['raw']['Value'],'MPN':'ORDERABLE-Y'});self.assertNotEqual(self.line('R1')['ids'],self.line('R2')['ids'])
 def test_settings_is_separate_and_undoable(self):
  before=deepcopy(self.ws.state['vendor_export_settings']);ae.configure(self.ws,{'profiles':['pcbpower']});self.assertEqual(ae.configuration(self.ws)['profiles'],['pcbpower']);self.assertEqual(self.ws.state['vendor_export_settings'],before);self.ws.undo();self.assertEqual(ae.configuration(self.ws)['profiles'],['jlcpcb'])
 def test_settings_survive_reload(self):ae.configure(self.ws,self.all_config());self.ws.save();self.assertEqual(ae.configuration(Workspace(Project(self.path)))['profiles'],list(ae.PROFILES))
 def test_stale_fingerprint_error(self):
  r=self.report();self.edit('R1',{'Value':'22k'})
  with self.assertRaisesRegex(ValueError,'stale'):ae.export(self.ws,fingerprint=r['fingerprint'])
 def test_source_change_refused(self):
  self.path.write_text(self.path.read_text()+'\n')
  with self.assertRaises(ValueError):self.report()

class AssemblyFormatTests(Fixture):
 report=AssemblyTests.report
 line=AssemblyTests.line
 all_config=AssemblyTests.all_config
 def test_csv_four_columns(self):b,_,_=ae.export(self.ws,fmt='csv');rows=list(csv.reader(io.StringIO(b.decode('utf-8-sig'))));self.assertEqual(rows[0],ae.PROFILES['jlcpcb']['headers']);self.assertTrue(all(len(r)==4 for r in rows))
 def test_single_file_multiple_profiles_refused(self):
  with self.assertRaises(ValueError):ae.export(self.ws,config=self.all_config(),fmt='xlsx')
 def test_review_required_cannot_export(self):
  with self.assertRaises(ValueError):ae.export(self.ws,config={'profiles':['hqpcb']},fmt='zip')
 def test_tsv_needs_review(self):
  with self.assertRaises(ValueError):ae.export(self.ws,fmt='tsv')
 def test_tsv_ack(self):b,_,_=ae.export(self.ws,config={'acknowledge_review_required':True},fmt='tsv');self.assertIn(b'\t',b)
 def test_excel_single_sheet_no_formulas_numeric_qty(self):
  self.edit('R1',{'MPN':'0000123-EXACT-CT'});b,_,_=ae.export(self.ws,config={'profiles':['pcbpower']},fmt='xlsx');z=zipfile.ZipFile(io.BytesIO(b));s=z.read('xl/worksheets/sheet1.xml');self.assertIn(b'0000123-EXACT-CT',s);self.assertNotIn(b'<f',s);self.assertNotIn('xl/worksheets/sheet2.xml',z.namelist());ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};root=ET.fromstring(s);qty=root.findall('.//m:row',ns)[1].findall('m:c',ns)[1];self.assertNotEqual(qty.attrib.get('t'),'inlineStr');self.assertIsNotNone(qty.find('m:v',ns))
 def test_package_files_all_profiles_and_hashes(self):
  b,_,_=ae.export(self.ws,config=self.all_config());z=zipfile.ZipFile(io.BytesIO(b));self.assertIsNone(z.testzip());manifest=json.loads(z.read('manifest.json'));self.assertEqual(len([n for n in z.namelist() if n.startswith('uploads/')]),2*len(ae.PROFILES))
  for n,meta in manifest['files'].items():self.assertEqual(meta['sha256'],sha(z.read(n)));self.assertEqual(meta['bytes'],len(z.read(n)))
 def test_all_dnp_audit_only(self):
  self.ws.edit([r['id'] for r in self.ws.rows()],BASE,{'dnp':True});b,_,_=ae.export(self.ws,config=self.all_config());z=zipfile.ZipFile(io.BytesIO(b));self.assertFalse(any(n.startswith('uploads/') for n in z.namelist()));self.assertEqual(json.loads(z.read('reports/REPORT.json'))['status'],'NO_ASSEMBLY_DEMAND')
 def test_formula_identifier_refused(self):self.edit('R1',{'MPN':'=SUM(1,2)'});r=self.report(profiles=['pcbpower']);self.assertEqual(r['status'],'BLOCKED')

class AssemblyCLITests(Fixture):
 def invoke(self,*args):
  out,err=io.StringIO(),io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main([str(a) for a in args])
  return code,out.getvalue(),err.getvalue()
 def test_list_no_project(self):code,out,err=self.invoke('assemblers','--list-profiles');self.assertEqual(code,0,err);self.assertIn('jlcpcb',out)
 def test_json_current_project(self):code,out,err=self.invoke('assemblers',self.path);self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['quantity_basis'],'per_board')
 def test_cli_all_zip(self):
  dest=self.dir/'assembly.zip';code,out,err=self.invoke('assemblers',self.path,'--all-profiles','--acknowledge-profile-review','--format','zip','--output',dest);self.assertEqual(code,0,err);self.assertTrue(zipfile.is_zipfile(dest))
 def test_cli_no_ack_no_output(self):
  dest=self.dir/'no.zip';code,out,err=self.invoke('assemblers',self.path,'--profile','hqpcb','--format','zip','--output',dest);self.assertEqual(code,3,err);self.assertFalse(dest.exists())
 def test_cli_no_overwrite(self):
  dest=self.dir/'keep.csv';dest.write_bytes(b'keep');code,_,_=self.invoke('assemblers',self.path,'--format','csv','--output',dest);self.assertNotEqual(code,0);self.assertEqual(dest.read_bytes(),b'keep')
 def test_cli_stdin_config(self):
  with patch('sys.stdin',io.StringIO('{"profiles":["pcbpower"]}')):code,out,err=self.invoke('assemblers',self.path,'--config','-')
  self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['profiles'][0]['id'],'pcbpower')
 def test_cli_save_source_only_forbidden(self):self.assertNotEqual(self.invoke('assemblers',self.path,'--save-settings','--source-only')[0],0)
 def test_cli_save_and_reload(self):
  code,out,err=self.invoke('assemblers',self.path,'--profile','pcbpower','--save-settings');self.assertEqual(code,0,err);self.assertEqual(ae.configuration(Workspace(Project(self.path)))['profiles'],['pcbpower'])
 def test_pipeline_outputs_assembly_and_native_scope_unchanged(self):
  c=dict(automation.default_pipeline(),variants=[BASE],reports=['checks'],formats=['csv'],assembler_exports={'profiles':['pcbpower']});r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'PASSED');self.assertTrue(list((self.dir/'run').rglob('pcbpower_BOM_PER_BOARD.xlsx')));self.assertTrue(automation.verify_run(self.dir/'run')['valid'])
 def test_failed_profile_gate_no_uploads_or_bom(self):
  c=dict(automation.default_pipeline(),variants=[BASE],reports=['checks'],formats=['csv'],assembler_exports={'profiles':['hqpcb']});r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'FAILED');self.assertFalse(list((self.dir/'run').rglob('*.csv')));self.assertTrue((self.dir/'run/001/assembler-review.json').exists())

class AssemblyHTTPTests(unittest.TestCase):
 def setUp(self):self.app=Application(demo=True);self.server=Server(self.app);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(3);shutil.rmtree(self.app.demo_directory,ignore_errors=True)
 def post(self,path,body=None,token=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Content-Type':'application/json','Origin':self.server.origin}
  if token:headers['X-Bom-Token']=self.app.token
  c.request('POST','/api/assemblers/'+path,json.dumps(body or {}),headers);r=c.getresponse();data=r.read();c.close();return r.status,data
 def test_list_profiles(self):s,b=self.post('profiles');self.assertEqual(s,200);self.assertEqual(set(json.loads(b)),set(ae.PROFILES))
 def test_preview(self):s,b=self.post('preview');self.assertEqual(s,200);self.assertEqual(json.loads(b)['schema'],ae.REPORT)
 def test_export(self):s,b=self.post('export',{'format':'zip'});self.assertEqual(s,200);self.assertTrue(zipfile.is_zipfile(io.BytesIO(b)))
 def test_auth_required(self):self.assertEqual(self.post('preview',token=False)[0],401)
 def test_save(self):s,b=self.post('settings',{'config':{'profiles':['sierra']}});self.assertEqual(s,200);self.assertEqual(ae.configuration(self.app.workspace)['profiles'],['sierra'])
 def test_stale(self):self.assertEqual(self.post('export',{'fingerprint':'0'*64})[0],400)
 def test_review_gate(self):self.assertEqual(self.post('export',{'config':{'profiles':['hqpcb']}})[0],400)
 def test_unknown_endpoint(self):self.assertEqual(self.post('bad')[0],400)

if __name__=='__main__':unittest.main()
