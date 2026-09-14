"""v0.3 bounded regression fixtures — not manufacturer/production qualification."""
from test_core import Fixture
from bomstudio import bulkedit, evidence, intelligence
from bomstudio.footprints import package_hint,pad_data,Inspector,symbol_pins
from bomstudio.sexpr import parse
from bomstudio.native import BASE, Project
from bomstudio.engine import Workspace
from bomstudio.exporters import table, export
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import base64,csv,io,json,unittest,zipfile

class GridTests(Fixture):
 def entry(self,ref='R1',**changes):return [{'ids':[self.row(ref)['id']],'changes':changes or {'Value':'22k'}}]
 def apply(self,entries):
  p=bulkedit.preview(self.ws,BASE,entries);return bulkedit.apply(self.ws,BASE,entries,p['fingerprint'],'EDIT',True)
 def test_preview_no_mutation(self):
  s=self.ws._serialize();h=dict(self.ws.project.hashes);bulkedit.preview(self.ws,BASE,self.entry());self.assertEqual(s,self.ws._serialize());self.ws.project.check_unchanged();self.assertEqual(h,self.ws.project.hashes)
 def test_value_edit_and_single_undo(self):
  r=self.apply(self.entry());self.assertEqual(self.row('R1')['fields']['Value'],'22k');self.assertEqual(len(self.ws.undo_stack),1);self.ws.undo();self.assertEqual(self.row('R1')['fields']['Value'],'10k');self.ws.redo();self.assertEqual(self.row('R1')['fields']['Value'],'22k')
 def test_footprint_native_preserved_until_apply(self):
  self.apply(self.entry(Footprint='Resistor_SMD:R_0805_2012Metric'));self.ws.project.check_unchanged();self.assertIn('0805',self.row('R1')['fields']['Footprint'])
 def test_mpn_edit(self):self.apply(self.entry(MPN='NEW-SUFFIX'));self.assertEqual(self.row('R1')['fields']['MPN'],'NEW-SUFFIX')
 def test_shared_expansion_visible(self):
  p=bulkedit.preview(self.ws,BASE,self.entry('R101',Value='3k3'));refs={e['reference'] for e in p['events']};self.assertTrue({'R101','R201'}<=refs);self.assertTrue(any(e['expanded'] for e in p['events']))
 def test_shared_conflicts_rejected(self):
  with self.assertRaises(ValueError):bulkedit.preview(self.ws,BASE,self.entry('R101',Value='3k3')+self.entry('R201',Value='4k7'))
 def test_active_variant_does_not_edit_base(self):
  e=self.entry(Value='1k');p=bulkedit.preview(self.ws,'Economy',e);bulkedit.apply(self.ws,'Economy',e,p['fingerprint'],'EDIT');self.assertEqual(self.row('R1')['fields']['Value'],'10k');self.assertEqual(self.row('R1','Economy')['fields']['Value'],'1k')
 def test_stale_preview_rejected(self):
  e=self.entry();p=bulkedit.preview(self.ws,BASE,e);self.edit('C1',{'Notes':'changed'})
  with self.assertRaises(ValueError):bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'EDIT')
 def test_typed_confirmation(self):
  e=self.entry();p=bulkedit.preview(self.ws,BASE,e)
  with self.assertRaises(ValueError):bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'APPLY')
 def test_variable_loss_gate(self):
  self.ws.set_variables('project',{'RV':'10k'});self.edit('R1',{'Value':'${RV}'})
  e=self.entry();p=bulkedit.preview(self.ws,BASE,e);self.assertGreater(p['variable_losses'],0)
  with self.assertRaises(ValueError):bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'EDIT')
 def test_raw_variable_preserved(self):
  self.ws.set_variables('project',{'RV':'10k'});self.apply(self.entry(Value='${RV}'));self.assertEqual(self.row('R1')['raw']['Value'],'${RV}')
 def test_alias_edits_original_property(self):
  self.edit('R1',{'Custom MPN':'OLD','MPN':''});self.ws.set_aliases({'MPN':['Custom MPN']});self.apply(self.entry(MPN='NEW'));self.assertEqual(self.row('R1')['raw']['Custom MPN'],'NEW')
 def test_computed_not_editable(self):
  for key in ('Qty','Reference','Required','Sheet'):
   with self.subTest(key=key),self.assertRaises(ValueError):bulkedit.preview(self.ws,BASE,self.entry(**{key:'x'}))
 def test_flag_boolean(self):self.apply(self.entry(InBOM=False));self.assertFalse(self.row('R1')['flags']['in_bom'])
 def test_population(self):self.apply(self.entry(Assembly='DNI'));self.assertTrue(self.row('R1')['flags']['dnp']);self.assertEqual(self.row('R1')['fields']['Assembly'],'DNI')
 def test_population_reset(self):
  self.apply(self.entry(Assembly='DNI'));self.apply(self.entry(Assembly=None));self.assertEqual(self.row('R1')['fields']['Assembly'],'FIT')
 def test_atomic_invalid_second_cell(self):
  s=self.ws._serialize()
  with self.assertRaises(ValueError):bulkedit.preview(self.ws,BASE,self.entry()+self.entry('C1',InBOM='false'))
  self.assertEqual(s,self.ws._serialize())
 def test_group_any_custom_field(self):
  self.edit('R1',{'Bin':'A'});self.edit('C1',{'Bin':'A'});g=bulkedit.groups(self.ws,BASE,['Bin']);group=next(x for x in g['groups'] if x['keys']['Bin']=='A');self.assertEqual(group['count'],2);self.assertIn('Value',group['mixed'])
 def test_group_mixed_mpn_no_export_merge(self):
  self.edit('R1',{'MPN':'OTHER'});g=bulkedit.groups(self.ws,BASE,['Footprint']);self.assertTrue(any('MPN' in x['mixed'] for x in g['groups']));t=table(self.ws,BASE,'Engineering');self.assertGreater(t['groups'],len(g['groups']))
 def test_no_group_individual(self):self.assertEqual(len(bulkedit.groups(self.ws,BASE,[])['groups']),11)
 def test_group_raw_vs_resolved(self):
  self.ws.set_variables('project',{'RV':'10k'});self.edit('R1',{'Value':'${RV}'})
  a=bulkedit.groups(self.ws,BASE,['Value'],False);b=bulkedit.groups(self.ws,BASE,['Value'],True);self.assertEqual(len(b['groups']),len(a['groups'])+1)
 def test_save_reopen(self):
  self.apply(self.entry());self.ws.save();w=Workspace(Project(self.path));self.assertEqual(next(r for r in w.rows() if r['ref']=='R1')['fields']['Value'],'22k')
 def test_source_change_invalidates(self):
  e=self.entry();p=bulkedit.preview(self.ws,BASE,e);self.path.write_text(self.path.read_text()+'\n')
  with self.assertRaises(ValueError):bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'EDIT')

class EvidenceTests(Fixture):
 def rec(self,**kw):return dict(manufacturer='DEMO Components',mpn='DEMO-R0603-10K',supplier='DigiKey',stock='1,000',region='IN',source_url='https://example.invalid/product',observed_at=datetime.now(timezone.utc).isoformat(),**kw)
 def add(self,record):
  payload={'format':'manual','record':record};p=evidence.preview(self.ws,payload);return evidence.apply(self.ws,payload,p['fingerprint'],'IMPORT',True)
 def test_exact_identity_suffix_kept(self):self.assertNotEqual(evidence.identity('TI','ABC-TR'),evidence.identity('TI','ABC'))
 def test_manufacturer_case_whitespace(self):self.assertEqual(evidence.identity(' A  B ','X'),evidence.identity('a b','X'))
 def test_mpn_case_not_guessed(self):self.assertNotEqual(evidence.identity('a','pA'),evidence.identity('a','PA'))
 def test_stock_commas(self):self.assertEqual(evidence.validate_record(self.rec())['stock'],1000)
 def test_stock_unknown_not_zero(self):r=self.rec();r['stock']='';self.assertIsNone(evidence.validate_record(r)['stock'])
 def test_in_stock_text_rejected(self):
  r=self.rec();r['stock']='In Stock'
  with self.assertRaises(ValueError):evidence.validate_record(r)
 def test_localized_stock_ambiguous(self):
  for text in ('1.234','1,23','>=100','1K','-1'):
   with self.subTest(text=text),self.assertRaises(ValueError):evidence.integer(text)
 def test_explicit_zero(self):self.assertEqual(evidence.integer('0'),0)
 def test_link_safety(self):
  for url in ('javascript:alert(1)','file:///tmp/x','https://u:p@site.com','http://site.com'):
   with self.subTest(url=url),self.assertRaises(ValueError):evidence.safe_url(url)
 def test_manual_import_review_required(self):
  payload={'format':'manual','record':self.rec()};p=evidence.preview(self.ws,payload)
  with self.assertRaises(ValueError):evidence.apply(self.ws,payload,p['fingerprint'],'IMPORT',False)
 def test_manual_import_no_component_edits(self):
  before=self.ws.rows();self.add(self.rec());self.assertEqual(self.ws.rows(),before);self.assertEqual(len(self.ws.state['evidence']),1)
 def test_import_undo(self):self.add(self.rec());self.ws.undo();self.assertEqual(self.ws.state['evidence'],[])
 def test_import_dedupe(self):r=self.rec();self.add(r);self.add(r);self.assertEqual(len(self.ws.state['evidence']),1)
 def test_remove_undo(self):self.add(self.rec());ids=[r['id'] for r in self.ws.state['evidence']];evidence.remove(self.ws,ids);self.assertFalse(self.ws.state['evidence']);self.ws.undo();self.assertTrue(self.ws.state['evidence'])
 def test_csv_mapping(self):
  _,info=evidence.table_info({'text':'Manufacturer Part Number,Manufacturer,Quantity Available\nABC,Acme,5\n'});self.assertEqual(info['mapping']['mpn'],'Manufacturer Part Number');self.assertEqual(info['mapping']['stock'],'Quantity Available')
 def test_bad_rows_atomic(self):
  payload={'text':'MPN,Manufacturer,Stock\nABC,Acme,5\nDEF,Acme,maybe\n'};p=evidence.preview(self.ws,payload);self.assertEqual(len(p['errors']),1)
  with self.assertRaises(ValueError):evidence.apply(self.ws,payload,p['fingerprint'],'IMPORT',True)
  self.assertFalse(self.ws.state['evidence'])
 def test_no_mpn_mapping(self):
  with self.assertRaises(ValueError):evidence.preview(self.ws,{'text':'Part Number,Stock\nABC,5\n'})
 def test_json_schema(self):
  with self.assertRaises(ValueError):evidence.preview(self.ws,{'format':'json','text':'{"schema":"future","records":[]}'})
 def test_import_undated_remains_undated(self):r=self.rec();r['observed_at']='';self.add(r);self.assertEqual(self.ws.state['evidence'][0]['observed_at'],'')
 def test_negative_dimension_rejected(self):
  r=self.rec(pitch_mm='-1')
  with self.assertRaises(ValueError):evidence.validate_record(r)
 def test_duplicate_pins_rejected(self):
  r=self.rec(pin_numbers='1,1,2')
  with self.assertRaises(ValueError):evidence.validate_record(r)
 def test_pin_names_json(self):self.assertEqual(evidence.validate_record(self.rec(pin_names='{"1":"GND"}'))['pin_names'],{'1':'GND'})
 def test_xlsx_read_actual_export(self):
  data,_,_=export(self.ws,BASE,'Purchasing','xlsx');rows,sheets=evidence.xlsx_table(base64.b64encode(data).decode());self.assertTrue(rows);self.assertTrue(sheets)
 def test_bad_xlsx_rejected(self):
  with self.assertRaises(ValueError):evidence.xlsx_table(base64.b64encode(b'not a zip').decode())
 def test_xlsx_formula_rejected(self):
  data,_,_=export(self.ws,BASE,'Purchasing','xlsx');inp=zipfile.ZipFile(io.BytesIO(data));out=io.BytesIO()
  with zipfile.ZipFile(out,'w') as z:
   for name in inp.namelist():
    b=inp.read(name)
    if name=='xl/worksheets/sheet1.xml':b=b.replace(b'<is>',b'<f>1+1</f><is>',1)
    z.writestr(name,b)
  with self.assertRaises(ValueError):evidence.xlsx_table(base64.b64encode(out.getvalue()).decode())
 def test_future_date_imported_but_not_eligible(self):
  r=self.rec();r['observed_at']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat();self.add(r);h=intelligence.run(self.ws);d=next(d for d in h['demand'] if d['mpn']==r['mpn']);self.assertEqual(d['stock']['status'],'unknown')
 def test_source_not_network_fetched(self):self.add(self.rec());self.assertEqual(len(self.ws.state['evidence']),1)

class PhysicalTests(Fixture):
 def geometry(self,body=''):
  root=self.dir/'libraries';d=root/'Resistor_SMD.pretty';d.mkdir(parents=True,exist_ok=True)
  text='(footprint "R_0603_1608Metric" (pad "1" smd rect (at -1 0) (size 1 1)) (pad "2" smd rect (at 1 0) (size 1 1)) '+body+')'
  (d/'R_0603_1608Metric.kicad_mod').write_text(text);intelligence.configure(self.ws,{'library_roots':[str(root)]});return root
 def package_record(self,**kw):
  r=dict(manufacturer='DEMO Components',mpn='DEMO-R0603-10K',source_url='https://example.invalid/datasheet',supplier='Manual',package='0603 (1608 Metric)',pin_count='2',mounting='SMD',reviewed=True,**kw)
  self.ws.state['evidence'].append(evidence.validate_record(r));return r
 def codes(self,ref='R1'):return {i['code'] for i in intelligence.run(self.ws)['issues'] if i['reference']==ref}
 def test_sot23_not_23_pins(self):h=package_hint('Package_TO_SOT_SMD:SOT-23');self.assertEqual(h['family'],'SOT-23');self.assertIsNone(h['pin_count'])
 def test_sot23_5_pins(self):self.assertEqual(package_hint('SOT-23-5')['pin_count'],5)
 def test_passive_metric_pair(self):self.assertEqual(package_hint('R_0603_1608Metric')['family'],package_hint('0603 (1608 Metric)')['family'])
 def test_bare_0603_ambiguous(self):self.assertIsNone(package_hint('0603')['family'])
 def test_qfn_name(self):h=package_hint('QFN-32-1EP_5x5mm_P0.5mm');self.assertEqual(h['pin_count'],32);self.assertTrue(h['exposed_pad']);self.assertEqual(h['pitch_mm'],.5);self.assertEqual(h['body_mm'],[5,5])
 def test_unique_pads_not_apertures(self):
  p=pad_data(parse('(footprint "F" (pad "1" smd rect (at 0 0)) (pad "1" thru_hole circle (at 0 1)) (pad "" smd rect (at 2 0)) (pad "" np_thru_hole circle (at 2 2)))'));self.assertEqual(p['unique_electrical_pads'],1)
 def test_library_read(self):self.geometry();p=Inspector(self.ws).inspect(self.row('R1'));self.assertEqual(p['selected']['pin_numbers'],['1','2']);self.assertEqual(p['selected_source'],'library')
 def test_missing_geometry_unknown(self):self.assertIn('FOOTPRINT_FILE_UNKNOWN',self.codes())
 def test_missing_part_evidence_unknown(self):self.geometry();self.assertIn('PART_PACKAGE_UNKNOWN',self.codes())
 def test_matching_not_certified(self):self.geometry();self.package_record();h=intelligence.run(self.ws);p=next(p for p in h['parts'] if p['reference']=='R1');self.assertEqual(p['package_status'],'screened_only');self.assertNotIn('qualified',p['package_status'])
 def test_pin_count_conflict(self):self.geometry();r=self.package_record();self.ws.state['evidence'][0]['pin_count']=3;self.assertIn('PART_PAD_COUNT_MISMATCH',self.codes())
 def test_pin_set_conflict(self):self.geometry();self.package_record(pin_numbers='1,2,3');self.assertIn('PART_PAD_SET_MISMATCH',self.codes())
 def test_mounting_conflict(self):self.geometry();self.package_record();self.ws.state['evidence'][0]['mounting']='THT';self.assertIn('MOUNTING_MISMATCH',self.codes())
 def test_package_family_conflict(self):self.geometry();self.package_record();self.ws.state['evidence'][0]['package']='SOIC-8';self.assertIn('PACKAGE_FAMILY_MISMATCH',self.codes())
 def test_exact_mpn_required(self):self.geometry();self.package_record();self.ws.state['evidence'][0]['mpn']='DEMO-R0603-10K-REEL';self.assertIn('PART_PACKAGE_UNKNOWN',self.codes())
 def test_part_value_conflict(self):self.geometry();self.package_record(value='22k');self.assertIn('PART_VALUE_MISMATCH',self.codes())
 def test_part_value_equivalent(self):self.geometry();self.package_record(value='10000Ohm');self.assertNotIn('PART_VALUE_MISMATCH',self.codes())
 def test_ratings_metadata_conflict(self):self.geometry();self.package_record(voltage_rating='16 V');self.edit('R1',{'Voltage Rating':'50V'});self.assertIn('RATING_METADATA_REVIEW',self.codes())
 def test_pin_function_conflict(self):self.geometry();self.package_record(pin_names={'1':'GND','2':'VCC'});self.assertIn('PIN_FUNCTION_REVIEW',self.codes())
 def test_board_mismatch(self):
  self.ws.project.pro_path.with_suffix('.kicad_pcb').write_text('(kicad_pcb (version 20260306) (footprint "Other:Wrong" (property "Reference" "R1") (pad "1" smd rect (at 0 0))))');self.assertIn('BOARD_ASSIGNMENT_MISMATCH',self.codes())
 def test_board_path_mismatch(self):
  self.ws.project.pro_path.with_suffix('.kicad_pcb').write_text('(kicad_pcb (version 20260306) (footprint "Resistor_SMD:R_0603_1608Metric" (property "Reference" "R1") (path "/wrong") (pad "1" smd rect (at 0 0))))');self.assertIn('BOARD_INSTANCE_MISMATCH',self.codes());self.assertIsNone(Inspector(self.ws).inspect(self.row('R1'))['selected'])
 def test_board_library_pad_difference(self):
  self.geometry();self.ws.project.pro_path.with_suffix('.kicad_pcb').write_text('(kicad_pcb (version 20260306) (footprint "Resistor_SMD:R_0603_1608Metric" (property "Reference" "R1") (pad "1" smd rect (at 0 0))))');self.assertIn('BOARD_LIBRARY_PAD_DIFFERENCE',self.codes())
 def test_symbol_missing_pad(self):self.geometry();p=self.dir/'libraries/Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod';p.write_text('(footprint "F" (pad "1" smd rect (at 0 0)))');self.assertIn('SYMBOL_PAD_MISSING',self.codes())
 def test_pad_inspection_no_write(self):self.geometry();before={p:p.read_bytes() for p in self.dir.rglob('*.kicad*')};intelligence.run(self.ws);self.assertEqual(before,{p:p.read_bytes() for p in before})

class StockAnalysisTests(Fixture):
 def offer(self,**kw):
  r=dict(manufacturer='DEMO Components',mpn='DEMO-R0603-10K',supplier='DigiKey',sku='ABC',stock=100,observed_at=datetime.now(timezone.utc).isoformat(),source_url='https://example.invalid/product',region='IN',reviewed=True);r.update(kw);return evidence.validate_record(r)
 def result(self,*records):
  self.ws.state['evidence']=list(records);return next(d for d in intelligence.run(self.ws)['demand'] if d['mpn']=='DEMO-R0603-10K')
 def test_no_money_no_keys_not_zero(self):self.assertEqual(self.result()['stock']['status'],'unknown')
 def test_recent_covered(self):self.assertEqual(self.result(self.offer())['stock']['status'],'observed_covered')
 def test_recent_shortage(self):self.assertEqual(self.result(self.offer(stock=0))['stock']['status'],'observed_shortage')
 def test_stale_unknown(self):self.assertEqual(self.result(self.offer(observed_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))['stock']['status'],'unknown')
 def test_region_unknown(self):self.assertEqual(self.result(self.offer(region='US'))['stock']['status'],'unknown')
 def test_mpn_suffix_unknown(self):self.assertEqual(self.result(self.offer(mpn='DEMO-R0603-10K-TR'))['stock']['status'],'unknown')
 def test_manufacturer_unknown(self):self.assertEqual(self.result(self.offer(manufacturer='OTHER'))['stock']['status'],'unknown')
 def test_missing_numeric_stock_unknown(self):self.assertEqual(self.result(self.offer(stock=''))['stock']['status'],'unknown')
 def test_unreviewed_unknown(self):self.assertEqual(self.result(self.offer(reviewed=False))['stock']['status'],'unknown')
 def test_no_source_unknown(self):self.assertEqual(self.result(self.offer(source_url=''))['stock']['status'],'unknown')
 def test_undated_unknown(self):self.assertEqual(self.result(self.offer(observed_at=''))['stock']['status'],'unknown')
 def test_demand_aggregates_exact(self):self.assertEqual(self.result()['per_board'],3) # R1/R2/R3 fitted; R4 DNP
 def test_boards_attrition(self):self.ws.settings({'boards':10,'attrition':10});self.assertEqual(self.result()['required'],33)
 def test_moq_multiple(self):d=self.result(self.offer(stock=9,moq=10,order_multiple=6));self.assertEqual(d['stock']['offers'][0]['order_quantity'],12);self.assertEqual(d['stock']['status'],'observed_shortage')
 def test_never_sum_offers(self):d=self.result(self.offer(stock=2),self.offer(supplier='Mouser',sku='OTHER',stock=2));self.assertEqual(d['required'],3);self.assertEqual(d['stock']['status'],'observed_shortage')
 def test_same_sku_latest_only(self):
  old=self.offer(stock=100,observed_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat());new=self.offer(stock=0);d=self.result(old,new);self.assertEqual(len(d['stock']['offers']),1);self.assertEqual(d['stock']['status'],'observed_shortage')
 def test_timezone_latest_not_lexical(self):
  clock=datetime(2026,9,9,18,tzinfo=timezone.utc);a=self.offer(stock=100,observed_at='2026-09-09T17:00:00+05:30');b=self.offer(stock=0,observed_at='2026-09-09T12:00:00Z');d=intelligence.stock_status({'required':2},[a,b],intelligence.DEFAULTS,clock);self.assertEqual(d['status'],'observed_shortage')
 def test_request_no_dnp_demand(self):
  self.edit('R3',{'dnp':True})
  data,_,_=intelligence.supplier_request(self.ws);rows=list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))));r=next(r for r in rows if r['Manufacturer Part Number']=='DEMO-R0603-10K');self.assertEqual(r['Quantity'],'2');self.assertNotIn('R3',r['Customer Reference'])
 def test_normalized_units(self):
  for a,b,ref in [('4k7','4700','R1'),('100n','0.1uF','C1'),('2u2','2.2uH','L1'),('R47','0.47Ohm','R1')]:self.assertEqual(intelligence.normalized_value(a,ref),intelligence.normalized_value(b,ref))
 def test_milli_mega_different(self):self.assertNotEqual(intelligence.normalized_value('1m','R1'),intelligence.normalized_value('1M','R1'))
 def test_no_ic_numeric_guess(self):self.assertIsNone(intelligence.normalized_value('10k','U1'))
 def test_wrong_unit_not_normalized(self):self.assertIsNone(intelligence.normalized_value('10uH','C1'))
 def test_equivalent_labels_not_mpn_conflict(self):self.edit('R1',{'Value':'10000Ohm'});self.assertFalse(any(i['code']=='MPN_CONFLICT' and 'R1' in i['reference'] for i in self.ws.checks()))
 def test_analyzer_normalization(self):self.edit('R1',{'Value':'10000Ohm'});a=intelligence.analyze(self.ws);self.assertEqual(a['summary']['normalization_groups'],1)
 def test_analyzer_candidate_not_approval(self):self.edit('R1',{'MPN':'ALT'});a=intelligence.analyze(self.ws);self.assertEqual(a['consolidation_candidates'][0]['status'],'candidate_needs_qualification')
 def test_analyzer_different_rating_blocks(self):self.edit('R1',{'MPN':'ALT','Tolerance':'1%'});self.edit('R2',{'Tolerance':'5%'});a=intelligence.analyze(self.ws);self.assertEqual(a['consolidation_candidates'][0]['status'],'blocked_by_recorded_differences')
 def test_analyzer_no_silent_edits(self):before=self.ws._serialize();intelligence.analyze(self.ws);self.assertEqual(before,self.ws._serialize())
 def test_settings_persist(self):intelligence.configure(self.ws,{'stock_age_hours':12});self.ws.save();w=Workspace(Project(self.path));self.assertEqual(w.state['health_settings']['stock_age_hours'],12)
 def test_settings_reject_nan(self):
  with self.assertRaises(ValueError):intelligence.configure(self.ws,{'stock_age_hours':float('nan')})

class NewNativeSyncTests(Fixture):
 def test_reviewed_value_writes_after_apply(self):
  ids=[self.row(ref)['id'] for ref in ('R1','R2','R3')];entries=[{'ids':ids,'changes':{'Value':'10000Ohm'}}]
  plan=bulkedit.preview(self.ws,BASE,entries);bulkedit.apply(self.ws,BASE,entries,plan['fingerprint'],'EDIT');self.ws.project.check_unchanged();self.native_apply()
  self.assertEqual(self.row('R2')['raw']['Value'],'10000Ohm');self.assertEqual(self.ws.project.by_id[self.row('R2')['id']].fields['Value'],'10000Ohm')
 def test_evidence_survives_native_sync(self):
  payload={'format':'manual','record':{'mpn':'DEMO-R0603-10K','manufacturer':'DEMO Components','stock':'10','region':'IN'}}
  plan=evidence.preview(self.ws,payload);evidence.apply(self.ws,payload,plan['fingerprint'],'IMPORT',True);self.edit('R1',{'Notes':'Reviewed edit'});self.native_apply();self.assertEqual(len(self.ws.state['evidence']),1);self.assertEqual(self.ws.state['evidence'][0]['stock'],10)

class InputHardeningTests(Fixture):
 def test_null_mpn_rejected(self):
  with self.assertRaises(ValueError):evidence.validate_record({'mpn':None})
 def test_malformed_sidecar_evidence_rejected(self):
  self.ws.state['evidence']=[{'id':'fake','mpn':'X','stock':'In Stock'}]
  with self.assertRaises(ValueError):self.ws._validate_state()
 def test_bad_grouping_state_rejected(self):
  self.ws.state['grouping']={'fields':['MPN','MPN'],'raw':False}
  with self.assertRaises(ValueError):self.ws._validate_state()
 def test_bad_health_state_rejected(self):
  self.ws.state['health_settings']={'stock_age_hours':'yesterday'}
  with self.assertRaises(ValueError):self.ws._validate_state()
 def test_null_stock_is_unknown(self):self.assertIsNone(evidence.validate_record({'mpn':'TEST','stock':None})['stock'])
 def test_package_body_height_optional(self):self.assertEqual(package_hint('QFN-32_5x5x0.9mm_P0.5mm')['body_mm'],[5,5])
 def test_library_nickname_not_pin_count(self):self.assertEqual(package_hint('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')['pin_count'],8)

if __name__=='__main__':unittest.main()
