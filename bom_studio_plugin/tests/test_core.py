from pathlib import Path
from copy import deepcopy
import csv
import io
import json
import shutil
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
from bomstudio.native import Project,BASE,read_flags,variants,sha
from bomstudio.engine import Workspace,Resolver,decimal_value
from bomstudio.sexpr import parse,apply_edits,properties,quote
from bomstudio.exporters import table,export,release,safe_csv,references
from bomstudio.writeback import compile_plan,apply_plan,_transaction

EXAMPLES=Path(__file__).resolve().parents[1]/'examples'

class Fixture(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name).resolve()
  # Isolate synthetic fixtures from installed KiCad libraries and user config.
  from unittest.mock import patch
  import os
  isolated={k:v for k,v in os.environ.items() if not k.upper().startswith('KICAD') and k.upper() not in ('PROGRAMFILES','PROGRAMFILES(X86)','APPDATA','XDG_CONFIG_HOME')}
  isolated.update(APPDATA=str(self.dir/'config'),XDG_CONFIG_HOME=str(self.dir/'config'))
  self.environment=patch.dict(os.environ,isolated,clear=True);self.environment.start();self.addCleanup(self.environment.stop)
  for f in EXAMPLES.glob('*.kicad_*'):shutil.copy2(f,self.dir/f.name)
  self.path=self.dir/'BOM_Demo.kicad_pro';self.ws=Workspace(Project(self.path))
 def tearDown(self):self.tmp.cleanup()
 def row(self,ref,variant=BASE):return next(r for r in self.ws.rows(variant) if r['ref']==ref)
 def edit(self,ref,changes,variant=BASE):self.ws.edit([self.row(ref)['id']],variant,changes)
 def native_apply(self):
  p=compile_plan(self.ws);self.ws,b=apply_plan(self.ws,p['fingerprint'],'APPLY',True);return b

class ParserTests(unittest.TestCase):
 def test_comments_quotes_unicode(self):
  n=parse(';header\n(root (field "a;()" "μΩ \\"q\\""))')
  self.assertEqual(n.one('field').val(1),'a;()')
 def test_property_private(self):self.assertEqual(properties(parse('(symbol (property private "MPN" "ABC"))'))['MPN'][0],'ABC')
 def test_unbalanced_rejected(self):
  for s in ['(a','(a))','(a) (b)','(a "bad)']:
   with self.subTest(s=s),self.assertRaises(ValueError):parse(s)
 def test_depth_limit(self):
  with self.assertRaises(ValueError):parse('(x '*515+')'*515)
 def test_exact_surgical_edit(self):
  s=';keep\n(root\n  (property "MPN" "OLD") (unrelated 123))\n';atom=properties(parse(s))['MPN'][2]
  self.assertEqual(apply_edits(s,[(atom.start,atom.end,'"NEW"')]),s.replace('"OLD"','"NEW"'))
 def test_overlap_rejected(self):
  with self.assertRaises(ValueError):apply_edits('abcdef',[(0,4,'x'),(3,5,'y')])
 def test_insert_coalescing(self):self.assertEqual(apply_edits('()',[(1,1,'a'),(1,1,'b')]),'(ab)')
 def test_native_bom_boolean_before_fix(self):
  n=parse('(path "/r" (variant (name "Old") (in_bom yes)))')
  self.assertFalse(variants(n,20260101)[0]['Old']['flags']['in_bom'])
 def test_native_bom_boolean_after_fix(self):
  n=parse('(path "/r" (variant (name "New") (in_bom yes)))')
  self.assertTrue(variants(n,20260306)[0]['New']['flags']['in_bom'])
 def test_base_bom_boolean_not_inverted(self):self.assertTrue(read_flags(parse('(symbol (in_bom yes))'))['in_bom'])
 def test_unknown_variant_record_reported(self):
  _,unknown=variants(parse('(path "/r" (variant (name "Future") (pin_map "x")))'),20260306)
  self.assertIn('pin_map',unknown)
 def test_reference_ranges(self):self.assertEqual(references(['R10','R3','R2','R1','C1'],True),'C1, R1–R3, R10')
 def test_leading_zero_ref_not_compressed(self):self.assertEqual(references(['R01','R02','R03'],True),'R01, R02, R03')

class WorkspaceTests(Fixture):
 def test_fixture_complete(self):self.assertEqual(len(self.ws.rows()),11);self.assertEqual(self.ws.checks(),[])
 def test_single_top_level_supported(self):self.assertTrue(self.ws.project.status()['native_write_supported'])
 def test_multiunit_counts_once(self):
  root=self.ws.project.root;doc=self.ws.project.documents[root];c=self.ws.project.components[5];m=c.members[0]
  original=doc.text[m.symbol.start:m.symbol.end]
  second=original.replace('(unit 1)','(unit 2)').replace(m.uuid,'22222222-2222-2222-2222-222222222222')
  root.write_text(doc.text[:doc.tree.end-1]+second+'\n'+doc.text[doc.tree.end-1:],encoding='utf-8')
  self.ws=Workspace(Project(self.path));self.assertEqual(len(self.ws.rows()),11);self.assertEqual(self.row(c.ref)['units'],2)
 def test_native_dni_retained(self):self.assertEqual(self.row('R3','Economy')['fields']['Assembly'],'DNI')
 def test_native_sheet_dnp_inherited(self):self.assertTrue(self.row('R201','Economy')['flags']['dnp'])
 def test_native_dnp_not_excluded(self):
  r=self.row('R3','Economy');self.assertTrue(r['flags']['in_bom']);self.assertTrue(r['flags']['dnp'])
 def test_placement_and_bom_are_independent(self):
  self.edit('R1',{'in_bom':False,'in_pos_files':True});r=self.row('R1')
  self.assertFalse(r['flags']['in_bom']);self.assertTrue(r['flags']['in_pos_files']);self.assertFalse(r['flags']['dnp'])
 def test_shared_sheet_base_edit_expands(self):
  self.edit('R101',{'MPN':'SHARED'});self.assertEqual(self.row('R201')['fields']['MPN'],'SHARED')
 def test_shared_sheet_variant_edit_is_per_instance(self):
  self.edit('R101',{'MPN':'ONLY_A'},'Economy');self.assertNotEqual(self.row('R201','Economy')['fields']['MPN'],'ONLY_A')
 def test_inherited_variant(self):
  self.ws.new_variant('Child','Economy');self.assertEqual(self.row('R3','Child')['fields']['Assembly'],'DNI');self.assertTrue(self.row('R201','Child')['flags']['dnp'])
 def test_reset_to_base_supersedes_native(self):
  self.edit('R3',{'dnp':None,'Assembly':None},'Economy');self.assertEqual(self.row('R3','Economy')['fields']['Assembly'],'FIT')
 def test_undo_redo(self):
  self.edit('R1',{'Notes':'changed'});self.ws.undo();self.assertNotEqual(self.row('R1')['raw']['Notes'],'changed');self.ws.redo();self.assertEqual(self.row('R1')['raw']['Notes'],'changed')
 def test_default_reserved_casefold(self):
  for name in ('default','<default>','ECONOMY'):
   with self.subTest(name=name),self.assertRaises(ValueError):self.ws.new_variant(name)
 def test_cannot_remove_parent(self):
  self.ws.new_variant('One');self.ws.new_variant('Two','One')
  with self.assertRaises(ValueError):self.ws.remove_variant('One')
 def test_no_native_variant_deletion(self):
  with self.assertRaises(ValueError):self.ws.remove_variant('Economy')
 def test_project_variables_recursive(self):self.assertIn('DEMO-A',self.row('R101')['fields']['Notes'])
 def test_sheet_variable_scope(self):self.assertIn('Channel B',self.row('R201')['fields']['Notes'])
 def test_variable_cycle_blocks_release(self):
  self.ws.set_variables('project',{'REV':'${REV}'});self.assertTrue(any(i['code']=='VARIABLE' for i in self.ws.checks()))
  with self.assertRaises(ValueError):export(self.ws,BASE,'Purchasing','csv')
 def test_missing_variable_detected(self):
  self.edit('R1',{'Notes':'${UNKNOWN}'});self.assertTrue(self.row('R1')['errors'])
 def test_reference_lookup(self):
  self.edit('C1',{'Notes':'${R1:MPN}'});self.assertEqual(self.row('C1')['fields']['Notes'],self.row('R1')['fields']['MPN'])
 def test_invalid_numeric_input(self):
  for value in ('NaN','Infinity','-1','1e10000000','abc'):
   self.assertIsNone(decimal_value(value))
 def test_aliases_do_not_rewrite_native(self):
  self.edit('R1',{'MPN':'','Manufacturer Part Number':'ALIAS'})
  self.assertEqual(self.row('R1')['fields']['MPN'],'ALIAS');self.assertEqual(self.row('R1')['raw']['MPN'],'')
 def test_text_dnp_not_silently_inferred(self):
  self.edit('R1',{'Assembly':'DNP'});self.assertEqual(self.row('R1')['fields']['Assembly'],'FIT');self.assertTrue(any(i['code']=='POPULATION_CONFLICT' for i in self.ws.checks()))
 def test_footprint_change_blocks_export(self):
  self.edit('R1',{'Footprint':'Other:Package'})
  with self.assertRaises(ValueError):export(self.ws,BASE,'Purchasing','csv')
 def test_duplicate_mpn_conflict(self):
  self.edit('R1',{'Value':'22k'});self.assertTrue(any(i['code']=='MPN_CONFLICT' for i in self.ws.checks()))
 def test_saved_workspace_does_not_change_source(self):
  hashes=dict(self.ws.project.hashes);self.edit('R1',{'Notes':'persist'});self.ws.save();self.assertTrue(all(sha(Path(p).read_bytes())==h for p,h in hashes.items()))
 def test_reopen_keeps_overrides(self):
  self.edit('R1',{'Notes':'persist'});self.ws.save();self.ws=Workspace(Project(self.path));self.assertEqual(self.row('R1')['raw']['Notes'],'persist')
 def test_concurrent_sidecar_save_blocked(self):
  self.ws.save();self.ws.sidecar.write_text('{}')
  with self.assertRaises(ValueError):self.ws.save()
 def test_source_drift_blocks_after_reopen(self):
  self.ws.save();p=self.ws.project.root;p.write_text(p.read_text()+'\n');self.ws=Workspace(Project(self.path))
  self.assertTrue(any(i['code']=='SOURCE_DRIFT' for i in self.ws.checks()))
  with self.assertRaises(ValueError):export(self.ws,BASE,'Purchasing','csv')
 def test_rebase_requires_confirmation(self):
  with self.assertRaises(ValueError):self.ws.acknowledge_sources('yes')
 def test_csv_preview_no_mutation(self):
  before=self.ws._serialize();p=self.ws.csv_preview('Reference,UnitPrice\nR1,7.20\n');self.assertEqual(p['count'],1);self.assertEqual(before,self.ws._serialize())
 def test_csv_import_and_undo(self):
  self.ws.csv_apply('Reference,UnitPrice\nR1,7.20\nR2,8.20\n',BASE);self.ws.undo();self.assertEqual(self.row('R1')['fields']['UnitPrice'],'1.20')
 def test_csv_unknown_rejected(self):
  with self.assertRaises(ValueError):self.ws.csv_apply('Reference,MPN\nR999,no\n',BASE)
 def test_csv_duplicates_rejected(self):
  with self.assertRaises(ValueError):self.ws.csv_apply('Reference,MPN\nR1,one\nR1,two\n',BASE)
 def test_csv_shared_conflict_rejected(self):
  with self.assertRaises(ValueError):self.ws.csv_apply('Reference,MPN\nR101,one\nR201,two\n',BASE)
 def test_alternate_approval_requires_review(self):
  with self.assertRaises(ValueError):self.ws.alternate('MPN',{'MPN':'ALT','status':'approved'})
 def test_baseline_diff(self):
  self.ws.snapshot();self.edit('R1',{'Notes':'new'});self.assertTrue(any(d['Reference']=='R1' for d in self.ws.baseline_diff()))
 def test_future_version_blocks(self):
  p=self.ws.project.root;p.write_text(p.read_text().replace('20260306','20270301'));self.ws=Workspace(Project(self.path));self.assertTrue(self.ws.project.blockers)
  with self.assertRaises(ValueError):export(self.ws,BASE,'Purchasing','csv')
 def test_draft_future_inspection_allowed(self):
  p=self.ws.project.root;p.write_text(p.read_text().replace('20260306','20270301'));self.ws=Workspace(Project(self.path))
  self.assertIn('DRAFT',export(self.ws,BASE,'Purchasing','csv',True)[1])
 def test_missing_sheet_never_silently_ignored(self):
  (self.dir/'Channel.kicad_sch').unlink()
  with self.assertRaises(ValueError):Project(self.path)
 def test_flat_multiple_roots_blocked(self):
  pro=json.loads(self.path.read_text());pro['schematic']['top_level_sheets'].append({'filename':'Channel.kicad_sch'});self.path.write_text(json.dumps(pro));self.assertTrue(Project(self.path).blockers)

class ExportTests(Fixture):
 def test_purchasing_excludes_dnp(self):
  p=table(self.ws,'Economy','Purchasing');col=p['columns'].index('Reference');refs=' '.join(r[col] for r in p['rows']);self.assertNotIn('R3',refs);self.assertNotIn('R201',refs)
 def test_required_moq_rounding(self):
  self.ws.settings({'boards':5,'attrition':10})
  p=table(self.ws,BASE,'Purchasing');lookup={c:i for i,c in enumerate(p['columns'])};r=next(r for r in p['rows'] if r[lookup['MPN']]=='DEMO-R0603-10K')
  self.assertEqual(r[lookup['Required']],17);self.assertEqual(r[lookup['OrderQty']],20)
 def test_conflicting_price_splits_groups(self):
  p=table(self.ws,BASE,'Purchasing')['groups'];self.edit('R1',{'UnitPrice':'9.99'});self.assertEqual(table(self.ws,BASE,'Purchasing')['groups'],p+1)
 def test_currencies_separate(self):
  self.edit('R1',{'Currency':'USD'});self.assertEqual(set(table(self.ws,BASE,'Purchasing')['totals']),{'INR','USD'})
 def test_unknown_price_not_zero(self):
  self.edit('J1',{'UnitPrice':''});p=table(self.ws,BASE,'Purchasing');self.assertEqual(p['unpriced_lines'],1)
 def test_stock_shortage_detected(self):
  self.edit('J1',{'Stock':'0'});self.assertTrue(any(i['code']=='STOCK_SHORTAGE' for i in table(self.ws,BASE,'Purchasing')['issues']))
 def test_csv_formula_injection(self):
  for v in ['=HYPERLINK("bad")','  +2+3','@SUM(A1)','\tvalue','-1+2']:
   self.assertTrue(safe_csv(v).startswith("'"))
 def test_html_escaped(self):
  self.edit('R1',{'Notes':'<script>alert(1)</script>'});data,_,_=export(self.ws,BASE,'Assembly','html');self.assertNotIn(b'<script>',data);self.assertIn(b'&lt;script&gt;',data)
 def test_xlsx_valid_xml_no_formulas(self):
  self.edit('R1',{'Notes':'=1+1'});data,_,_=export(self.ws,BASE,'Assembly','xlsx')
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   for name in z.namelist():
    if name.endswith(('.xml','.rels')):ET.fromstring(z.read(name))
   self.assertNotIn(b'<f>',z.read('xl/worksheets/sheet1.xml'))
   self.assertIn(b'=1+1',z.read('xl/worksheets/sheet1.xml'))
 def test_release_integrity_manifest(self):
  data,_,_=release(self.ws)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   m=json.loads(z.read('manifest.json'))
   self.assertEqual(len(m['variants']),3)
   for name,checksum in m['files'].items():self.assertEqual(sha(z.read(name)),checksum)
 def test_release_all_or_nothing(self):
  self.edit('R1',{'MPN':''},'Economy')
  with self.assertRaises(ValueError):release(self.ws)
 def test_bad_template_rejected(self):
  t=deepcopy(self.ws.state['templates']['Engineering']);t['columns']=[{'field':'Value','label':'duplicate'},{'field':'MPN','label':'duplicate'}]
  with self.assertRaises(ValueError):self.ws.template(t)
 def test_export_source_change_blocked(self):
  p=self.ws.project.root;p.write_text(p.read_text()+'\n')
  with self.assertRaises(ValueError):export(self.ws,BASE,'Purchasing','csv')
 def test_template_expression(self):
  t=deepcopy(self.ws.state['templates']['Engineering']);t['name']='Expression';t['columns'].append({'field':'${Reference}/${MPN}','label':'Summary'});self.ws.template(t)
  self.assertIn('/',table(self.ws,BASE,'Expression')['rows'][0][-1])

class NativeSyncTests(Fixture):
 def test_noop_preview(self):self.assertEqual(compile_plan(self.ws)['count'],0)
 def test_different_root_filename_roundtrip(self):
  new=self.dir/'DifferentRoot.kicad_sch';self.ws.project.root.rename(new)
  pro=json.loads(self.path.read_text());pro['schematic']['top_level_sheets'][0]['filename']=new.name;self.path.write_text(json.dumps(pro));self.ws=Workspace(Project(self.path))
  self.ws.set_variables('project',{'REV':'D'});self.native_apply();self.assertEqual(self.ws.project.variables['REV'],'D')
 def test_existing_field_roundtrip(self):
  self.edit('R1',{'Notes':'μΩ quote " and newline\nretained'});backup=self.native_apply();self.assertTrue((Path(backup)/'COMPLETED.txt').exists());self.assertIn('μΩ',self.row('R1')['raw']['Notes'])
 def test_new_property_roundtrip(self):
  self.edit('R1',{'ApprovedBy':'Engineer'});self.native_apply();self.assertEqual(self.row('R1')['raw']['ApprovedBy'],'Engineer')
 def test_base_shared_property_roundtrip(self):
  self.edit('R101',{'Notes':'same across instances'});self.native_apply();self.assertEqual(self.row('R201')['raw']['Notes'],'same across instances')
 def test_variant_dni_roundtrip(self):
  self.ws.new_variant('Assembly-X');self.ws.set_population([self.row('C1')['id']],'Assembly-X','DNI');self.native_apply();self.assertEqual(self.row('C1','Assembly-X')['fields']['Assembly'],'DNI')
 def test_inheritance_sheet_roundtrip(self):
  self.ws.new_variant('Derived','Economy');self.native_apply();self.assertTrue(self.row('R201','Derived')['flags']['dnp']);self.assertEqual(self.row('R3','Derived')['fields']['Assembly'],'DNI')
 def test_project_variables_roundtrip(self):
  self.ws.set_variables('project',{'REV':'B'});self.native_apply();self.assertEqual(self.ws.project.variables['REV'],'B')
 def test_workspace_variables_not_silently_baked(self):
  self.ws.set_variables('workspace',{'X':'1'})
  with self.assertRaises(ValueError):compile_plan(self.ws)
 def test_wayricad_scoped_expression_blocks_native(self):
  self.edit('R1',{'Notes':'${PROJECT:REV}'})
  with self.assertRaises(ValueError):compile_plan(self.ws)
 def test_bad_confirmation(self):
  p=compile_plan(self.ws)
  with self.assertRaises(ValueError):apply_plan(self.ws,p['fingerprint'],'yes',True)
 def test_stale_preview(self):
  p=compile_plan(self.ws);self.edit('R1',{'Notes':'after review'})
  with self.assertRaises(ValueError):apply_plan(self.ws,p['fingerprint'],'APPLY',True)
 def test_active_lock_prevents_write(self):
  self.edit('R1',{'Notes':'blocked'});p=compile_plan(self.ws);(self.dir/'~BOM_Demo.kicad_sch.lck').write_text('lock')
  with self.assertRaises(ValueError):apply_plan(self.ws,p['fingerprint'],'APPLY',True)
 def test_pre_fix_format_not_written(self):
  p=self.ws.project.root;p.write_text(p.read_text().replace('20260306','20260101'));self.ws=Workspace(Project(self.path))
  with self.assertRaises(ValueError):compile_plan(self.ws)
 def test_unrelated_source_preserved(self):
  self.edit('R1',{'Notes':'single edit'});before=self.ws.project.root.read_text();n=self.ws.project.documents[self.ws.project.root].tree.one('lib_symbols');original=before[n.start:n.end];self.native_apply();after=self.ws.project.root.read_text();self.assertIn(original,after)
 def test_unknown_project_keys_preserved(self):
  p=json.loads(self.path.read_text());p['custom_vendor_data']={'nested':[1,'x']};self.path.write_text(json.dumps(p));self.ws=Workspace(Project(self.path));self.ws.set_variables('project',{'REV':'C'});self.native_apply();self.assertEqual(json.loads(self.path.read_text())['custom_vendor_data'],{'nested':[1,'x']})
 def test_rollback_on_validator_failure(self):
  f=self.dir/'transaction.txt';f.write_bytes(b'original')
  def fail():raise ValueError('simulation failure')
  with self.assertRaises(ValueError):_transaction({f:b'new'},{f:sha(b'original')},self.dir/'backup',fail)
  self.assertEqual(f.read_bytes(),b'original');self.assertTrue((self.dir/'backup'/'FAILED.txt').exists())
 def test_concurrent_write_refused(self):
  f=self.dir/'transaction.txt';f.write_bytes(b'other')
  with self.assertRaises(ValueError):_transaction({f:b'new'},{f:sha(b'original')},self.dir/'backup')
  self.assertEqual(f.read_bytes(),b'other')

if __name__=='__main__':unittest.main()
