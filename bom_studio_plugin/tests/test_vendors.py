"""Distributor file contracts, not authenticated live-site acceptance."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import csv, io, json, zipfile, unittest, threading, http.client
import xml.etree.ElementTree as ET
from unittest.mock import patch
from test_core import Fixture
from bomstudio import vendor_export as ve, automation, cli, nativefirst
from bomstudio.native import BASE, Project, sha
from bomstudio.engine import Workspace
from bomstudio.server import Application, Server

class VendorFixture(Fixture):
 def setUp(self):
  super().setUp()
  self.ws.edit([r['id'] for r in self.ws.rows()],BASE,{'Supplier':'DigiKey','MOQ':'1','OrderMultiple':'1'})
  self.edit('C1',{'Supplier':'Mouser','Mouser Part Number':'001-CAP-CT'})
 def report(self,**c):return ve.preview(self.ws,BASE,c)
 def item(self,ref,report=None):return next(x for x in (report or self.report())['components'] if x['reference']==ref)
 def assign(self,ref,vendor,sku=None):
  row=self.row(ref);entry={'vendor':vendor,'signature':ve.part_signature(row)}
  if sku is not None:entry['sku']=sku
  return {'assignments':{BASE:{row['id']:entry}}}
 def get_line(self,ref,r=None):return next(l for v in (r or self.report())['vendors'] for l in v['lines'] if ref in [self.ws.project.by_id[x].ref for x in l['ids']])

class RoutingTests(VendorFixture):
 def test_two_vendors_and_reconciliation(self):
  r=self.report();s=r['summary'];self.assertEqual(s['vendors'],2);self.assertEqual(s['physical_components'],11);self.assertEqual(s['eligible_components'],10);self.assertEqual(s['routed_components']+s['unassigned_components']+s['blocked_components'],s['eligible_components'])
 def test_no_native_or_preference_mutation(self):
  before=self.ws._serialize();sources={str(p):p.read_bytes() for p in self.ws.project.documents};ve.export(self.ws,fmt='zip');self.assertEqual(before,self.ws._serialize());self.assertEqual(nativefirst.preferences(self.ws)['mode'],'native');self.assertTrue(all(Path(p).read_bytes()==b for p,b in sources.items()))
 def test_vendor_aliases(self):
  for name in ['Digi-Key','digi key','DIGIKEY Electronics']:
   self.edit('R1',{'Supplier':name});self.assertEqual(self.item('R1')['vendor_id'],'digikey')
 def test_generic_vendor_does_not_become_digikey(self):
  self.edit('R1',{'Supplier':'Local distributor'});self.assertTrue(self.item('R1')['vendor_id'].startswith('other-'));self.assertEqual(self.report()['summary']['vendors'],3)
 def test_ambiguous_vendor_blocked(self):
  self.edit('R1',{'Supplier':'DigiKey / Mouser'});self.assertEqual(self.item('R1')['status'],'blocked')
 def test_unassigned_report_not_silent_omit(self):
  self.edit('R1',{'Supplier':''});r=self.report();self.assertEqual(r['summary']['unassigned_components'],1)
  with self.assertRaisesRegex(ValueError,'Unassigned'):ve.package_files(r)
 def test_dnp_excluded(self):self.assertIn('R4',[r['reference'] for r in self.report()['excluded']])
 def test_bom_excluded_not_purchased(self):
  self.ws.edit([self.row('R1')['id']],BASE,{'in_bom':False});r=self.report();self.assertNotIn('R1',[r['reference'] for r in r['components']]);self.assertEqual(r['summary']['excluded_components'],2)
 def test_vendor_specific_sku_wins(self):self.assertEqual(self.item('C1')['sku'],'001-CAP-CT')
 def test_other_vendor_sku_not_used(self):
  self.edit('R1',{'Mouser Part Number':'M-SKU','DigiKey Part Number':'','SKU':''});self.assertEqual(self.item('R1')['sku'],'')
 def test_override_drops_old_generic_sku(self):
  self.assertEqual(self.item('R1',ve.preview(self.ws,BASE,self.assign('R1','Mouser')))['sku'],'')
 def test_override_uses_new_vendor_specific_sku(self):
  self.edit('R1',{'Mouser Part Number':'NEW-M'});r=ve.preview(self.ws,BASE,self.assign('R1','Mouser'));self.assertEqual(self.item('R1',r)['sku'],'NEW-M')
 def test_override_specific_sku(self):
  r=ve.preview(self.ws,BASE,self.assign('R1','Mouser','000-NEW-TR'));self.assertEqual(self.item('R1',r)['sku'],'000-NEW-TR')
 def test_override_stales_after_value_change(self):
  c=self.assign('R1','Mouser');self.edit('R1',{'Value':'22k'});r=ve.preview(self.ws,BASE,c);self.assertEqual(self.item('R1',r)['status'],'blocked')
 def test_missing_assignment_target_blocks(self):
  c={'assignments':{BASE:{'gone':{'vendor':'Mouser','signature':'a'*64}}}};r=ve.preview(self.ws,BASE,c);self.assertTrue(r['blocking_checks'])
 def test_override_scoped_to_variant(self):
  c=self.assign('R1','Mouser');a=ve.preview(self.ws,'Economy',c);self.assertEqual(self.item('R1',a)['vendor_id'],'digikey')
 def test_empty_explicit_mapping_stays_empty(self):
  self.edit('R1',{'VendorOverride':''});r=self.report(vendor_field='VendorOverride');self.assertEqual(self.item('R1',r)['status'],'unassigned')
 def test_custom_field_mapping(self):
  self.edit('R1',{'Procurement_Source':'Mouser'});r=self.report(vendor_field='Procurement_Source');self.assertEqual(self.item('R1',r)['vendor_id'],'mouser')
 def test_conflicting_vendor_aliases(self):
  self.edit('R1',{'Vendor':'Mouser'});self.assertEqual(self.item('R1')['status'],'blocked')
 def test_exact_part_suffixes_and_case_retained(self):
  self.edit('R1',{'MPN':'Part-AbC#PBF/TR','SKU':'000-LONG-CT'});r=self.item('R1');self.assertEqual(r['mpn'],'Part-AbC#PBF/TR');self.assertEqual(r['sku'],'000-LONG-CT')
 def test_formula_like_identity_blocked(self):
  self.edit('R1',{'SKU':'=WEBSERVICE("bad")'});self.assertEqual(self.item('R1')['status'],'blocked')
 def test_value_not_purchase_identity(self):
  self.edit('R1',{'MPN':'','SKU':''});self.assertEqual(self.item('R1')['status'],'blocked')
 def test_same_sku_conflicting_mpn_blocks_both(self):
  self.edit('R1',{'SKU':'SAME'});self.edit('C2',{'SKU':'SAME'});r=self.report();self.assertEqual(self.item('R1',r)['status'],'blocked');self.assertEqual(self.item('C2',r)['status'],'blocked')
 def test_variable_resolved_without_baking(self):
  self.edit('R1',{'Supplier':'${WHERE}'});self.ws.state['project_variables']['WHERE']='Mouser';r=self.report();self.assertEqual(self.item('R1',r)['vendor_id'],'mouser');self.assertEqual(self.row('R1')['raw']['Supplier'],'${WHERE}')
 def test_no_stock_inference(self):self.assertIn('No stock check',self.report()['notice'])
 def test_no_network_requests(self):
  with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):ve.export(self.ws,fmt='zip')

class QuantityAndFileTests(VendorFixture):
 def line(self,ref,report=None):return next(l for v in (report or self.report())['vendors'] for l in v['lines'] if ref in l['references'].split(', '))
 def test_quantity_moq_and_multiple(self):
  self.edit('R1',{'MOQ':'50','OrderMultiple':'12'});l=self.line('R1',self.report(boards=10,attrition_percent='5'));self.assertEqual([l[x] for x in ['installed_qty','required_qty','order_qty','overbuy_qty','upload_qty']],[10,11,60,49,60])
 def test_installed_basis(self):self.assertEqual(self.line('R1',self.report(boards=10,quantity_basis='installed'))['upload_qty'],10)
 def test_required_basis(self):self.assertEqual(self.line('R1',self.report(boards=10,attrition_percent='5',quantity_basis='required'))['upload_qty'],11)
 def test_invalid_order_multiple_blocked(self):
  self.edit('R1',{'OrderMultiple':'0'});self.assertEqual(self.item('R1')['status'],'blocked')
 def test_pool_identical_purchasing_identity(self):
  a=self.row('R1')['raw'];self.edit('R2',{k:v for k,v in a.items() if k in ('Value','MPN','Manufacturer','Footprint','InternalPN','SKU','MOQ','OrderMultiple')});l=self.line('R1');self.assertEqual(l['qty_per_board'],2);self.assertIn('R2',l['references'])
 def test_distinct_ratings_not_pooled(self):
  a=self.row('R1')['raw'];self.edit('R2',{k:v for k,v in a.items() if k in ('Value','MPN','Manufacturer','Footprint','InternalPN','SKU','MOQ','OrderMultiple')});self.edit('R2',{'Voltage':'100V'});self.assertEqual(self.line('R1')['qty_per_board'],1)
 def test_skus_not_stripped_for_packaging(self):
  self.edit('R1',{'SKU':'SKU-CT'});self.edit('R2',{'SKU':'SKU-TR'});self.assertNotEqual(self.line('R1')['sku'],self.line('R2')['sku'])
 def test_csv_supplier_headers(self):
  data,_,_=ve.export(self.ws,fmt='csv',vendor='Mouser');rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))));self.assertEqual(rows[0],ve.PROFILES['mouser']['headers']);self.assertEqual(rows[1][0],'001-CAP-CT');self.assertEqual(rows[1][2],'1')
 def test_xlsx_single_header_sheet_and_numeric_quantity(self):
  data,_,_=ve.export(self.ws,fmt='xlsx',vendor='mouser');z=zipfile.ZipFile(io.BytesIO(data));self.assertNotIn('xl/worksheets/sheet2.xml',z.namelist());ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};tree=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));cells={c.get('r'):c for c in tree.findall('.//s:c',ns)};self.assertEqual(cells['A2'].get('t'),'inlineStr');self.assertEqual(cells['A2'].find('.//s:t',ns).text,'001-CAP-CT');self.assertEqual(cells['C2'].find('s:v',ns).text,'1');self.assertIsNone(cells['C2'].find('s:f',ns));self.assertEqual(len(ET.fromstring(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',ns)),1)
 def test_conventional_ooxml_default_namespaces(self):
  data,_,_=ve.export(self.ws,fmt='xlsx',vendor='mouser');z=zipfile.ZipFile(io.BytesIO(data))
  for n in ['[Content_Types].xml','xl/workbook.xml','xl/_rels/workbook.xml.rels']:
   self.assertNotIn(b'<ns0:',z.read(n));ET.fromstring(z.read(n))
 def test_tsv_data(self):
  data,_,_=ve.export(self.ws,fmt='tsv',vendor='DigiKey');self.assertIn('\tQuantity\t',data.decode('utf-8-sig'))
 def test_zip_manifest_and_private_audit(self):
  data,_,_=ve.export(self.ws,fmt='zip');z=zipfile.ZipFile(io.BytesIO(data));m=json.loads(z.read('manifest.json'));self.assertEqual(m['status'],'READY_FOR_REVIEW');self.assertIn('reports/UNASSIGNED.csv',z.namelist());self.assertTrue(all(sha(z.read(n))==x['sha256'] for n,x in m['files'].items()));self.assertEqual(len([n for n in z.namelist() if n.startswith('uploads/')]),4)
 def test_partial_is_explicitly_labelled(self):
  self.edit('R1',{'Supplier':''});data,name,_=ve.export(self.ws,fmt='zip',allow_partial=True);z=zipfile.ZipFile(io.BytesIO(data));self.assertTrue('PARTIAL' in name);self.assertTrue(all('PARTIAL' in n for n in z.namelist() if n.startswith('uploads/')));self.assertIn('R1',z.read('reports/UNASSIGNED.csv').decode())
 def test_partial_never_bypasses_engineering_errors(self):
  self.ws.project.blockers.append('rule area needs validation')
  with self.assertRaisesRegex(ValueError,'BOM checks'):ve.export(self.ws,fmt='zip',allow_partial=True)
 def test_chunk_files_are_not_truncated(self):
  r=self.report(profiles={'digikey':{'max_lines':2}});files=ve.package_files(r);names=[n for n in files if n.startswith('uploads/DigiKey') and n.endswith('.csv')];self.assertGreater(len(names),1);count=sum(len(list(csv.reader(io.StringIO(files[n].decode('utf-8-sig')))))-1 for n in names);self.assertEqual(count,next(v['line_count'] for v in r['vendors'] if v['id']=='digikey'))
 def test_single_file_refuses_chunk_overflow(self):
  with self.assertRaisesRegex(ValueError,'ZIP'):ve.export(self.ws,config={'profiles':{'digikey':{'max_lines':1}}},fmt='csv',vendor='digikey')
 def test_custom_profile(self):
  self.edit('R1',{'Supplier':'Custom Shop'});c={'profiles':{'custom':{'name':'Custom Shop','aliases':['CS'],'headers':['Part','Pieces'],'keys':['mpn','upload_qty']}}};r=self.report(**c);v=next(x for x in r['vendors'] if x['id']=='custom');self.assertEqual(ve.upload_table(v)[0],['Part','Pieces'])
 def test_custom_value_formula_not_exported(self):
  self.edit('R1',{'Value':'+formula'});r=self.report(profiles={'digikey':{'headers':['SKU','Qty','Value'],'keys':['sku','upload_qty','value']}});self.assertEqual(self.item('R1',r)['status'],'blocked')
 def test_all_dnp_is_audit_only_not_unknown_demand(self):
  self.ws.edit([r['id'] for r in self.ws.rows()],BASE,{'dnp':True});r=self.report();self.assertEqual(r['status'],'NO_PURCHASING_DEMAND');files=ve.package_files(r);self.assertFalse(any(n.startswith('uploads/') for n in files));self.assertEqual(json.loads(files['manifest.json'])['status'],'NO_PURCHASING_DEMAND')
 def test_all_unassigned_cannot_be_upload_package(self):
  self.ws.edit([r['id'] for r in self.ws.rows()],BASE,{'Supplier':''})
  with self.assertRaisesRegex(ValueError,'No safely routed'):ve.export(self.ws,allow_partial=True)
 def test_partial_single_requires_companion_audit(self):
  self.edit('R1',{'Supplier':''})
  with self.assertRaisesRegex(ValueError,'require ZIP'):ve.export(self.ws,fmt='csv',vendor='mouser',allow_partial=True)
 def test_nested_format_invalid(self):
  with self.assertRaises(ValueError):ve.validate_config({'formats':[{}]})
 def test_control_character_upload_cell_refused(self):
  with self.assertRaises(ValueError):ve.safe_upload_cell('x\n=1')
 def test_settings_persist_and_do_not_enforce(self):
  state=deepcopy(self.row('R1')['raw']);ve.configure(self.ws,{'boards':20});self.ws.save();w=Workspace(Project(self.path));self.assertEqual(ve.configuration(w)['boards'],20);self.assertEqual(state,next(r['raw'] for r in w.rows() if r['ref']=='R1'))
 def test_mapping_undo(self):ve.configure(self.ws,{'boards':25});self.ws.undo();self.assertIsNone(ve.configuration(self.ws)['boards'])
 def test_preview_fingerprint_no_clock_dependency(self):self.assertEqual(self.report()['fingerprint'],self.report()['fingerprint'])
 def test_export_stale_fingerprint_refused(self):
  r=self.report();self.edit('R1',{'MOQ':'2'})
  with self.assertRaisesRegex(ValueError,'stale'):ve.export(self.ws,fingerprint=r['fingerprint'])
 def test_json_available_even_with_unassigned(self):
  self.edit('R1',{'Supplier':''});data,_,_=ve.export(self.ws,fmt='json');self.assertEqual(json.loads(data)['summary']['unassigned_components'],1)

class VendorConfigTests(unittest.TestCase):
 def test_reject_invalid_inputs(self):
  for bad in [{'boards':True},{'boards':0},{'boards':1.5},{'attrition_percent':'NaN'},{'attrition_percent':'101'},{'quantity_basis':'reels'},{'formats':[]},{'formats':['csv','csv']},{'unknown':1},{'schema':'future'},{'profiles':{'../bad':{}}},{'profiles':{'x':{'name':'Mouser'}}},{'profiles':{'x':{'headers':['=bad'],'keys':['sku']}}},{'assignments':{BASE:{'x':{'vendor':'DigiKey'}}}}]:
   with self.subTest(bad=bad),self.assertRaises(ValueError):ve.validate_config(bad)
 def test_default_is_fresh_copy(self):a=ve.validate_config();a['profiles']['x']={};self.assertEqual(ve.validate_config()['profiles'],{})
 def test_bad_url(self):
  with self.assertRaises(ValueError):ve.validate_config({'profiles':{'x':{'url':'file:///etc/passwd'}}})

class VendorCLIPipelineTests(VendorFixture):
 def invoke(self,*args):
  out,err=io.StringIO(),io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main([str(a) for a in args])
  return code,out.getvalue(),err.getvalue()
 def test_cli_json(self):
  self.ws.save();code,out,err=self.invoke('vendors',self.path);self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['summary']['vendors'],2)
 def test_cli_output_zip(self):
  self.ws.save();dest=self.dir/'upload.zip';code,out,err=self.invoke('vendors',self.path,'--format','zip','--output',dest);self.assertEqual(code,0,err);self.assertTrue(zipfile.is_zipfile(dest))
 def test_cli_preserves_existing_output(self):
  self.ws.save();dest=self.dir/'upload.zip';dest.write_bytes(b'keep');code,_,_=self.invoke('vendors',self.path,'--format','zip','--output',dest);self.assertNotEqual(code,0);self.assertEqual(dest.read_bytes(),b'keep')
 def test_cli_incomplete_has_report_exit_three(self):
  self.edit('R1',{'Supplier':''});self.ws.save();dest=self.dir/'report.json';code,_,_=self.invoke('vendors',self.path,'--output',dest);self.assertEqual(code,3);self.assertEqual(json.loads(dest.read_text())['summary']['unassigned_components'],1)
 def test_cli_failed_binary_has_no_file(self):
  self.edit('R1',{'Supplier':''});self.ws.save();dest=self.dir/'upload.zip';code,out,err=self.invoke('vendors',self.path,'--format','zip','--output',dest);self.assertEqual(code,3,err);self.assertFalse(dest.exists());self.assertFalse(json.loads(out)['data']['output_created'])
 def test_cli_explicit_partial(self):
  self.edit('R1',{'Supplier':''});self.ws.save();dest=self.dir/'upload.zip';code,out,err=self.invoke('vendors',self.path,'--format','zip','--allow-partial','--output',dest);self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['status'],'PARTIAL')
 def test_cli_save_forbids_source_only(self):
  self.assertNotEqual(self.invoke('vendors',self.path,'--save-settings','--source-only')[0],0)
 def test_cli_save_mappings(self):
  self.ws.save();code,out,err=self.invoke('vendors',self.path,'--save-settings','--boards','7');self.assertEqual(code,0,err);self.assertEqual(ve.configuration(Workspace(Project(self.path)))['boards'],7)
 def test_cli_stdin_config(self):
  self.ws.save()
  with patch('sys.stdin',io.StringIO('{"boards":42}')):code,out,err=self.invoke('vendors',self.path,'--config','-')
  self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['boards'],42)
 def test_pipeline_success_with_vendor_files(self):
  c=dict(automation.default_pipeline(),variants=[BASE],reports=['checks'],formats=['csv'],vendor_exports={'formats':['csv']});r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'PASSED');self.assertTrue(list((self.dir/'run/001/vendors/uploads').glob('*.csv')));self.assertTrue(automation.verify_run(self.dir/'run')['valid'])
 def test_pipeline_no_partial_silent_release(self):
  self.edit('R1',{'Supplier':''});c=dict(automation.default_pipeline(),variants=[BASE],reports=['checks'],formats=['csv'],vendor_exports={});r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'FAILED');self.assertFalse(list((self.dir/'run').rglob('*.csv')));self.assertTrue((self.dir/'run/001/vendor-routing.json').exists())
 def test_pipeline_disabled_unchanged(self):
  c=dict(automation.default_pipeline(),variants=[BASE],reports=['checks'],formats=['csv']);r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'PASSED');self.assertFalse((self.dir/'run/001/vendors').exists())

class VendorHTTPTests(unittest.TestCase):
 def setUp(self):
  self.app=Application(demo=True);self.server=Server(self.app);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(3)
 def post(self,path,body={},token=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={'Content-Type':'application/json','Origin':self.server.origin}
  if token:headers['X-Bom-Token']=self.app.token
  c.request('POST','/api/vendors/'+path,json.dumps(body),headers);r=c.getresponse();b=r.read();c.close();return r.status,b
 def test_preview(self):
  code,body=self.post('preview');self.assertEqual(code,200);self.assertEqual(json.loads(body)['schema'],ve.REPORT)
 def test_export(self):
  code,body=self.post('export',{'format':'zip'});self.assertEqual(code,200);self.assertTrue(zipfile.is_zipfile(io.BytesIO(body)))
 def test_auth_required(self):self.assertEqual(self.post('preview',token=False)[0],401)
 def test_config_save(self):
  code,b=self.post('settings',{'config':{'boards':4}});self.assertEqual(code,200);self.assertEqual(ve.configuration(self.app.workspace)['boards'],4)
 def test_unknown_operation(self):self.assertGreaterEqual(self.post('bad')[0],400)
 def test_fingerprint_check(self):self.assertGreaterEqual(self.post('export',{'fingerprint':'0'*64})[0],400)

if __name__=='__main__':unittest.main()
