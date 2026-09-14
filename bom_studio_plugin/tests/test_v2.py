"""v0.2: export controls, portable templates and reviewed native field schemas."""
from copy import deepcopy
import csv, io, json, zipfile
import xml.etree.ElementTree as ET
from test_core import Fixture
from bomstudio import catalog, enforcement
from bomstudio.engine import Resolver, Workspace
from bomstudio.native import BASE, Project
from bomstudio.exporters import table, export, MIME
from bomstudio.sexpr import properties


def profile(*names):
 return {'name':'Team fields','fields':[{'name':n,'aliases':[],'default':'','visible':False,'url':False,'required':False} for n in names]}

class CatalogTests(Fixture):
 def test_upgrade_has_starters(self):self.assertIn('JLCPCB assembly CSV',self.ws.state['templates'])
 def test_view_save_reopen(self):
  catalog.set_view(self.ws,{'columns':['MPN','Reference']},'Buyer');self.ws.save();w=Workspace(Project(self.path));self.assertEqual(w.state['view']['columns'],['MPN','Reference']);self.assertIn('Buyer',w.state['view_presets'])
 def test_view_does_not_delete_data(self):
  before=self.ws.rows();catalog.set_view(self.ws,{'columns':['Reference']});self.assertEqual(before,self.ws.rows())
 def test_view_empty_rejected(self):
  with self.assertRaises(ValueError):catalog.set_view(self.ws,{'columns':[]})
 def test_view_duplicate_rejected(self):
  with self.assertRaises(ValueError):catalog.set_view(self.ws,{'columns':['MPN','MPN']})
 def test_view_undo(self):
  catalog.set_view(self.ws,{'columns':['Reference']});self.ws.undo();self.assertEqual(self.ws.state['view']['columns'],[])
 def test_bundle_excludes_rows_variables_paths(self):
  self.ws.set_variables('project',{'SECRET':'123456'});b=catalog.bundle(self.ws);s=json.dumps(b);self.assertNotIn('123456',s);self.assertNotIn(str(self.dir),s);self.assertNotIn('source_hashes',s);self.assertNotIn('rows',b)
 def test_single_bundle(self):
  b=catalog.bundle(self.ws,'templates','Engineering');self.assertEqual(len(b['templates']),1);self.assertEqual(b['field_profiles'],[])
 def test_import_keep_both(self):
  s=json.dumps(catalog.bundle(self.ws,'templates','Engineering'));p=catalog.import_preview(self.ws,s);self.assertEqual(p['items'][0]['target'],'Engineering (imported)');catalog.import_apply(self.ws,s);self.assertIn('Engineering (imported)',self.ws.state['templates'])
 def test_import_replace(self):
  b=catalog.bundle(self.ws,'templates','Engineering');b['templates'][0]['description']='TEAM';catalog.import_apply(self.ws,json.dumps(b),'replace');self.assertEqual(self.ws.state['templates']['Engineering']['description'],'TEAM')
 def test_import_skip(self):
  s=json.dumps(catalog.bundle(self.ws,'templates','Engineering'));before=self.ws._serialize();catalog.import_apply(self.ws,s,'skip');self.assertEqual(before,self.ws._serialize())
 def test_import_future_version_rejected(self):
  b=catalog.bundle(self.ws);b['schema']=99
  with self.assertRaises(ValueError):catalog.parse_bundle(json.dumps(b))
 def test_import_duplicate_json_keys_rejected(self):
  with self.assertRaises(ValueError):catalog.parse_bundle('{"schema":1,"schema":1}')
 def test_import_prototype_key_rejected(self):
  with self.assertRaises(ValueError):catalog.parse_bundle('{"__proto__":{}}')
 def test_manage_duplicate_rename_delete(self):
  catalog.manage(self.ws,'templates','duplicate','Engineering','Mine');catalog.manage(self.ws,'templates','rename','Mine','Team');self.assertEqual(self.ws.state['templates']['Team']['name'],'Team');catalog.manage(self.ws,'templates','delete','Team');self.assertNotIn('Team',self.ws.state['templates'])
 def test_import_definition_only_no_native_changes(self):
  hashes=self.ws.project.hashes;catalog.import_apply(self.ws,json.dumps(catalog.bundle(self.ws)));self.ws.project.check_unchanged();self.assertEqual(hashes,self.ws.project.hashes);self.assertEqual(self.ws.state['field_schema_edits'],{})

class ExportV2Tests(Fixture):
 def template(self,columns,options=None,**extra):
  t=deepcopy(self.ws.state['templates']['Engineering']);t.update(name='Test',columns=[dict(field=f,label=l) for f,l in columns],**extra);t['options']=options or {};self.ws.template(t);return t
 def test_minimal_imported_template_defaults(self):
  self.ws.template({'name':'Tiny','columns':[{'field':'MPN','label':'MPN'}]});self.assertEqual(table(self.ws,BASE,'Tiny')['groups'],11)
 def test_column_order_and_hidden(self):
  t=self.template([('MPN','Part'),('Reference','Refs'),('Notes','Hidden')]);t['columns'][-1]['export']=False;self.ws.template(t);p=table(self.ws,BASE,'Test');self.assertEqual(p['columns'],['Part','Refs']);self.assertEqual(len(p['rows'][0]),2)
 def test_hidden_export_does_not_delete_source(self):
  t=self.template([('MPN','Part'),('Notes','Notes')]);t['columns'][-1]['export']=False;self.ws.template(t);self.assertIn('Notes',self.row('R1')['raw'])
 def test_no_export_columns_rejected(self):
  t=self.template([('MPN','MPN')]);t['columns'][0]['export']=False
  with self.assertRaises(ValueError):self.ws.template(t)
 def test_all_formats_generate(self):
  for fmt in MIME:
   if fmt=='zip':continue
   with self.subTest(fmt=fmt):data,name,mime=export(self.ws,BASE,'Engineering',fmt);self.assertGreater(len(data),30);self.assertTrue(mime)
 def test_ascii_escapes_not_replaces(self):
  self.edit('R1',{'Notes':'Ω μ é 😀'});self.template([('Notes','Notes')],group_by=[]);data=export(self.ws,BASE,'Test','ascii')[0].decode('ascii');self.assertIn('\\u03a9',data);self.assertIn('\\xe9',data);self.assertIn('\\U0001f600',data);self.assertNotIn('?',data)
 def test_ascii_strict_rejects(self):
  self.edit('R1',{'Notes':'Ω'});self.template([('Notes','Notes')],{'ascii_policy':'error'},group_by=[])
  with self.assertRaises(ValueError):export(self.ws,BASE,'Test','ascii')
 def test_text_utf8(self):
  self.edit('R1',{'Notes':'Ω'});self.template([('Notes','Notes')],group_by=[]);self.assertIn('Ω',export(self.ws,BASE,'Test','txt')[0].decode())
 def test_csv_semicolon_lf_quoted_no_bom(self):
  self.template([('Reference','Refs'),('MPN','Part')],{'encoding':'utf-8','line_ending':'lf','quoting':'all'},delimiter=';');data=export(self.ws,BASE,'Test','csv')[0];self.assertTrue(data.startswith(b'"Refs";"Part"\n'));self.assertNotIn(b'\r',data)
 def test_csv_ascii_charset(self):
  self.template([('MPN','MPN')],{'encoding':'ascii'});self.assertIn('us-ascii',export(self.ws,BASE,'Test','csv')[2])
 def test_csv_cp1252_error_no_replacement(self):
  self.edit('R1',{'Notes':'Ω'});self.template([('Notes','Notes')],{'encoding':'cp1252'})
  with self.assertRaises(ValueError):export(self.ws,BASE,'Test','csv')
 def test_virtual_columns_quantity_item(self):
  self.template([('${QUANTITY}','Quantity'),('${ITEM_NUMBER}','Line'),('${SYMBOL_LIBRARY}:${SYMBOL_NAME}','Library ID')]);p=table(self.ws,BASE,'Test');self.assertFalse([i for i in p['issues'] if i['code']=='TEMPLATE_VARIABLE']);self.assertTrue(all(int(r[0])>=1 for r in p['rows']));self.assertEqual([int(r[1]) for r in p['rows']],list(range(1,p['groups']+1)))
 def test_header_project_variable(self):
  self.ws.set_variables('project',{'COL':'Manufacturer PN'});self.template([('MPN','${COL}')]);self.assertEqual(table(self.ws,BASE,'Test')['columns'],['Manufacturer PN'])
 def test_header_context_error(self):
  self.template([('MPN','${REFERENCE}')]);self.assertTrue(any(i['code']=='TEMPLATE_HEADER_VARIABLE' for i in table(self.ws,BASE,'Test')['issues']))
 def test_raw_value_expressions(self):
  self.edit('R1',{'Notes':'${PROJECTNAME}'});self.template([('Reference','Ref'),('Notes','Notes')],{'text_mode':'raw'},group_by=[]);self.assertIn(['R1','${PROJECTNAME}'],table(self.ws,BASE,'Test')['rows'])
 def test_raw_group_reference_not_first_only(self):
  self.template([('Reference','Refs'),('MPN','MPN')],{'text_mode':'raw'});p=table(self.ws,BASE,'Test');self.assertTrue(any(',' in r[0] or '–' in r[0] for r in p['rows']))
 def test_xml_parse_and_escape(self):
  self.edit('R1',{'Notes':'<&"'});self.template([('Notes','Notes')]);root=ET.fromstring(export(self.ws,BASE,'Test','xml')[0]);self.assertEqual(root.get('schema'),'wayricad-bom-1');self.assertTrue(any(n.text=='<&"' for n in root.iter('cell')))
 def test_jsonlines_parse(self):
  lines=export(self.ws,BASE,'Engineering','jsonl')[0].decode().splitlines();self.assertEqual(json.loads(lines[0])['type'],'metadata');self.assertTrue(all(json.loads(s)['type']=='bom_line' for s in lines[1:]))
 def test_ods_package_structure(self):
  data=export(self.ws,BASE,'Engineering','ods')[0]
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   self.assertEqual(z.namelist()[0],'mimetype');self.assertEqual(z.getinfo('mimetype').compress_type,zipfile.ZIP_STORED);ET.fromstring(z.read('content.xml'));ET.fromstring(z.read('META-INF/manifest.xml'));self.assertNotIn(b'table:formula',z.read('content.xml'))
 def test_future_industry_format_not_faked(self):
  with self.assertRaises(ValueError):export(self.ws,BASE,'Engineering','ipc2581')

class FieldSchemaTests(Fixture):
 def enforce(self,p,**options):
  proposal=enforcement.preview(self.ws,p,options);self.assertEqual(proposal['errors'],[],proposal['errors'][:3]);enforcement.apply(self.ws,proposal['fingerprint'],'ENFORCE',True);return proposal
 def test_preview_no_mutation(self):
  before=self.ws._serialize();enforcement.preview(self.ws,profile('MPN','TeamCode'));self.assertEqual(before,self.ws._serialize());self.ws.project.check_unchanged()
 def test_merge_add_all_sheets_variants(self):
  self.enforce(profile('MPN','TeamCode'))
  for v in [BASE,*self.ws.state['variants']]:self.assertTrue(all('TeamCode' in r['raw'] for r in self.ws.rows(v)))
 def test_dnp_dni_flags_unchanged(self):
  before={v:[(r['flags'],r['fields']['Assembly']) for r in self.ws.rows(v)] for v in [BASE,*self.ws.state['variants']]};self.enforce(profile('MPN'),mode='exact');self.assertEqual(before,{v:[(r['flags'],r['fields']['Assembly']) for r in self.ws.rows(v)] for v in before})
 def test_exact_deletes_extras_but_protects_standard(self):
  self.enforce(profile('MPN'),mode='exact');r=self.row('R1');self.assertNotIn('Notes',r['raw']);self.assertIn('Footprint',r['raw']);self.assertEqual(r['raw']['Reference'],'R1')
 def test_enforce_requires_typed_phrase(self):
  p=enforcement.preview(self.ws,profile('MPN'))
  with self.assertRaises(ValueError):enforcement.apply(self.ws,p['fingerprint'],'yes',True)
 def test_destructive_ack_required(self):
  p=enforcement.preview(self.ws,profile('MPN'),{'mode':'exact'})
  with self.assertRaises(ValueError):enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',False)
 def test_stale_preview_blocked(self):
  p=enforcement.preview(self.ws,profile('MPN'));self.edit('R1',{'Notes':'changed'})
  with self.assertRaises(ValueError):enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',True)
 def test_source_drift_blocked(self):
  p=enforcement.preview(self.ws,profile('MPN'));self.ws.project.root.write_text(self.ws.project.root.read_text()+'\n')
  with self.assertRaises(ValueError):enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',True)
 def test_undo_single_operation(self):
  before=self.ws.rows();self.enforce(profile('MPN'),mode='exact');self.ws.undo();self.assertEqual(before,self.ws.rows());self.ws.redo();self.assertNotIn('Notes',self.row('R1')['raw'])
 def test_merge_native_roundtrip_and_reference_preservation(self):
  original={str(d.path):[properties(s)['Reference'][0] for s in d.tree.nodes('symbol')] for d in self.ws.project.documents.values()};self.enforce(profile('MPN','TeamCode'));self.native_apply();self.assertTrue(all('TeamCode' in r['raw'] for r in self.ws.rows()));after={str(d.path):[properties(s)['Reference'][0] for s in d.tree.nodes('symbol')] for d in self.ws.project.documents.values()};self.assertEqual(original,after)
 def test_exact_native_roundtrip(self):
  self.enforce(profile('MPN','Manufacturer'),mode='exact');self.native_apply()
  for v in [BASE,*self.ws.state['variants']]:self.assertTrue(all('Notes' not in r['raw'] for r in self.ws.rows(v)))
 def test_native_project_defaults_correct_key(self):
  p=profile('TeamCode');p['fields'][0].update(visible=True,url=True);self.enforce(p);self.native_apply();native=self.ws.project.pro['schematic']['drawing']['field_names'];self.assertIn({'name':'TeamCode','visible':True,'url':True},native)
 def test_enforce_stages_does_not_write(self):
  self.enforce(profile('TeamCode'));self.ws.save();self.ws.project.check_unchanged();self.assertTrue(self.ws.state['field_schema_edits'])
 def test_alias_migrate_preserves_expression(self):
  self.edit('R1',{'Mfr Part Number':'${PN}','MPN':''});self.ws.set_variables('project',{'PN':'PRESERVED'});p=profile('MPN');p['fields'][0]['aliases']=['Mfr Part Number'];self.enforce(p);r=self.row('R1');self.assertEqual(r['raw']['MPN'],'${PN}');self.assertNotIn('Mfr Part Number',r['raw'])
 def test_alias_conflict_blocks_without_picking(self):
  self.edit('R1',{'Mfr Part Number':'DIFFERENT'});p=profile('MPN');p['fields'][0]['aliases']=['Mfr Part Number'];plan=enforcement.preview(self.ws,p);self.assertTrue(any('Conflicting' in e['message'] for e in plan['errors']))
 def test_defaults_fill_not_overwrite(self):
  self.edit('R1',{'TeamCode':''});self.edit('R2',{'TeamCode':'keep'});p=profile('TeamCode');p['fields'][0]['default']='default';self.enforce(p,values='fill');self.assertEqual(self.row('R1')['raw']['TeamCode'],'default');self.assertEqual(self.row('R2')['raw']['TeamCode'],'keep')
 def test_reset_warns_variable_loss(self):
  self.edit('R1',{'Notes':'${PROJECTNAME}'});p=profile('Notes');p['fields'][0]['default']='reset';plan=self.enforce(p,values='reset');self.assertGreater(plan['variable_losses'],0);self.assertEqual(self.row('R1')['raw']['Notes'],'reset')
 def test_variables_in_physical_names_and_values(self):
  self.ws.set_variables('project',{'LABEL':'Part code','PN':'ABC'});self.edit('R1',{'Code_${LABEL}':'${PN}'});self.assertEqual(self.row('R1')['fields']['Code_Part code'],'ABC');self.enforce(profile('Code_${LABEL}'));self.assertEqual(self.row('R1')['raw']['Code_${LABEL}'],'${PN}');self.native_apply();self.assertEqual(self.row('R1')['raw']['Code_${LABEL}'],'${PN}')
 def test_bake_names_values_is_explicit(self):
  self.ws.set_variables('project',{'LABEL':'Part code','PN':'ABC'});self.edit('R1',{'Code_${LABEL}':'${PN}'});p=self.enforce(profile('Code_${LABEL}'),names='resolve',value_variables='bake');self.assertGreater(p['variable_losses'],0);self.assertEqual(self.row('R1')['raw']['Code_Part code'],'ABC');self.assertNotIn('Code_${LABEL}',self.row('R1')['raw']);self.assertEqual(self.ws.state['project_variables']['PN'],'ABC')
 def test_variable_name_collision_blocked(self):
  self.ws.set_variables('project',{'A':'Same','B':'Same'});p=enforcement.preview(self.ws,profile('Code_${A}','Code_${B}'));self.assertTrue(any('collision' in e['message'].lower() for e in p['errors']))
 def test_shared_baked_sheet_variable_blocked(self):
  p=profile('${SHEETNAME}');p=enforcement.preview(self.ws,p,{'names':'resolve','register_native':False});self.assertTrue(any('Shared-sheet' in e['message'] for e in p['errors']))
 def test_deleted_field_crossreference_detected(self):
  self.edit('C1',{'Trace':'${R1:Notes}'});p=enforcement.preview(self.ws,profile('Trace'),{'mode':'exact'});self.assertTrue(p['errors'])
 def test_protected_names_rejected(self):
  for n in ('Reference','Footprint','Assembly','ki_hidden','Sim.Device'):
   with self.subTest(n=n),self.assertRaises(ValueError):catalog.validate_profile(profile(n))
 def test_parent_edits_still_inherited(self):
  self.ws.new_variant('Child','Economy');self.enforce(profile('TeamCode'));self.edit('R1',{'TeamCode':'from base'});self.assertEqual(self.row('R1','Child')['raw']['TeamCode'],'from base');self.edit('R1',{'TeamCode':'from parent'},'Economy');self.assertEqual(self.row('R1','Child')['raw']['TeamCode'],'from parent');self.edit('R1',{'TeamCode':'child'},'Child');self.edit('R1',{'TeamCode':'new base'});self.assertEqual(self.row('R1','Child')['raw']['TeamCode'],'child')
 def test_variant_reset_after_enforcement(self):
  self.enforce(profile('TeamCode'));self.edit('R1',{'TeamCode':'base'});self.edit('R1',{'TeamCode':'variant'},'Economy');self.edit('R1',{'TeamCode':None},'Economy');self.assertEqual(self.row('R1','Economy')['raw']['TeamCode'],'base')
 def test_new_variant_inherits_enforced_schema(self):
  self.enforce(profile('MPN'),mode='exact');self.ws.new_variant('New');self.assertNotIn('Notes',self.row('R1','New')['raw']);self.native_apply();self.assertNotIn('Notes',self.row('R1','New')['raw'])
 def test_schema_order_survives_save(self):
  self.enforce(profile('TeamZ','TeamA'));self.ws.save();self.ws=Workspace(Project(self.path));self.native_apply();m=self.ws.project.by_id[self.row('R1')['id']].members[0];keys=list(properties(m.symbol));self.assertLess(keys.index('TeamZ'),keys.index('TeamA'))
 def test_profile_required_checked(self):
  p=profile('TeamCode');p['fields'][0]['required']=True;self.enforce(p);self.assertTrue(any(i['code']=='MISSING_FIELD' and 'TeamCode' in i['message'] for i in self.ws.checks()))
 def test_expression_expansion_bounded(self):
  variables={'V0':'A'*1000};variables.update({f'V{i}':('${V'+str(i-1)+'}')*10 for i in range(1,8)});r=Resolver(variables);text=r.text('${V7}');self.assertTrue(r.errors);self.assertLess(len(text),300000)


class GeneratedFieldTests(Fixture):
 def test_generated_field_value_guard(self):
  with self.assertRaises(ValueError):self.edit('R1',{'${REV}':'different'})
 def test_generated_field_effective_value_and_display_name(self):
  self.ws.set_variables('project',{'REV':'D'});self.edit('R1',{'${REV}':'${REV}'})
  row=self.row('R1');self.assertEqual(row['fields']['REV'],'D');self.assertEqual(row['resolved_names']['${REV}'],'REV');self.assertFalse(row['errors'])
 def test_generated_new_field_auto_links_default(self):
  self.ws.set_variables('project',{'TEAM':'Hardware'});p=enforcement.preview(self.ws,profile('${TEAM}'));self.assertFalse(p['errors'],p['errors']);enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',True)
  self.assertTrue(all(r['raw']['${TEAM}']=='${TEAM}' for r in self.ws.rows()));self.native_apply();self.assertEqual(self.row('R1')['fields']['TEAM'],'Hardware')
 def test_generated_wrong_profile_default_blocks_enforcement(self):
  self.ws.set_variables('project',{'TEAM':'Hardware'});p=profile('${TEAM}');p['fields'][0]['default']='different';self.assertTrue(enforcement.preview(self.ws,p)['errors'])
 def test_generated_cannot_bake_only_value(self):
  self.assertTrue(enforcement.preview(self.ws,profile('${REV}'),{'value_variables':'bake'})['errors'])
 def test_generated_explicit_bake_name_and_value(self):
  self.ws.set_variables('project',{'TEAM':'Hardware'});self.edit('R1',{'${TEAM}':'${TEAM}'})
  p=enforcement.preview(self.ws,profile('${TEAM}'),{'names':'resolve','value_variables':'bake'});self.assertFalse(p['errors'],p['errors']);self.assertTrue(p['variable_losses']);enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',True)
  self.assertEqual(self.row('R1')['raw']['Hardware'],'Hardware');self.native_apply()
 def test_generated_mismatched_existing_raw_blocks_checks_and_sync(self):
  self.ws.state['base'][self.row('R1')['id']]={'${REV}':'unsafe'};self.assertTrue(self.row('R1')['errors'])
  from bomstudio.writeback import compile_plan
  with self.assertRaises(ValueError):compile_plan(self.ws)
 def test_generated_like_compound_is_independent(self):
  from bomstudio.native import is_generated_field
  self.assertTrue(is_generated_field('${TEAM}'));self.assertFalse(is_generated_field('Code_${TEAM}'));self.assertFalse(is_generated_field('${TEAM}_Code'));self.assertFalse(is_generated_field('${R1:MPN}'))
 def test_raw_alias_export_keeps_expression(self):
  self.ws.set_variables('project',{'PN':'ABC'});self.edit('R1',{'MPN':'','Mfr Part Number':'${PN}'})
  t=deepcopy(self.ws.state['templates']['Engineering']);t.update(name='Alias raw',columns=[{'field':'Reference','label':'Ref'},{'field':'MPN','label':'MPN'}],group_by=[],options={'text_mode':'raw'});self.ws.template(t)
  self.assertIn(['R1','${PN}'],table(self.ws,BASE,'Alias raw')['rows'])
 def test_lcsc_standard_header_alias(self):
  self.edit('R1',{'LCSC Part #':'C12345'});self.assertEqual(self.row('R1')['fields']['LCSC'],'C12345')


class ExpressionBoundaryTests(Fixture):
 def test_escaped_expression_not_silently_resolved(self):
  r=Resolver({'REV':'A'});self.assertEqual(r.text(r'\${REV}'),r'\${REV}');self.assertTrue(r.errors)
 def test_nested_name_not_partially_resolved(self):
  r=Resolver({'N':'REV','REV':'A'});self.assertEqual(r.text('${${N}}'),'${${N}}');self.assertTrue(r.errors)
 def test_math_expression_not_silently_certified(self):
  r=Resolver({});self.assertEqual(r.text('@{1+2}'),'@{1+2}');self.assertTrue(r.errors)
 def test_incomplete_expression_not_silently_certified(self):
  r=Resolver({});self.assertEqual(r.text('${MISSING'),'${MISSING');self.assertTrue(r.errors)


class FieldCaseTests(Fixture):
 def test_normalize_ordinary_field_case(self):
  self.edit('R1',{'MPN':'','mpn':'ABC'});p=enforcement.preview(self.ws,profile('MPN'));self.assertFalse(p['errors'],p['errors']);enforcement.apply(self.ws,p['fingerprint'],'ENFORCE',True);self.assertEqual(self.row('R1')['raw']['MPN'],'ABC');self.assertNotIn('mpn',self.row('R1')['raw'])
 def test_conflicting_case_variants_block(self):
  self.edit('R1',{'mpn':'OTHER'});self.assertTrue(enforcement.preview(self.ws,profile('MPN'))['errors'])


class VisibilityTests(Fixture):
 def test_new_field_uses_template_visibility(self):
  p=profile('TeamCode');p['fields'][0]['visible']=True;plan=enforcement.preview(self.ws,p);self.assertFalse(plan['errors']);self.assertTrue(any(e['action']=='visibility' for e in plan['events']));enforcement.apply(self.ws,plan['fingerprint'],'ENFORCE',True);self.native_apply()
  m=self.ws.project.by_id[self.row('R1')['id']].members[0];self.assertEqual(properties(m.symbol)['TeamCode'][1].one('hide').val(1),'no')
 def test_existing_visibility_not_changed_implicitly(self):
  before=[]
  for c in self.ws.project.components:
   for m in c.members:
    if 'MPN' in properties(m.symbol):before.append(m.doc.text[properties(m.symbol)['MPN'][1].start:properties(m.symbol)['MPN'][1].end])
  p=profile('MPN');p['fields'][0]['visible']=True;plan=enforcement.preview(self.ws,p);self.assertFalse(any(e['action']=='visibility' for e in plan['events']));enforcement.apply(self.ws,plan['fingerprint'],'ENFORCE',True);self.native_apply()
  after=[]
  for c in self.ws.project.components:
   for m in c.members:
    if 'MPN' in properties(m.symbol):after.append(m.doc.text[properties(m.symbol)['MPN'][1].start:properties(m.symbol)['MPN'][1].end])
  self.assertEqual(before,after)
