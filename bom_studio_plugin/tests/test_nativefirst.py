"""v0.8.1 native-authority regression tests; no real KiCad process implied."""
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_core import Fixture
from bomstudio import nativefirst as nf,field_registry as fr,nativebom,cli
from bomstudio.engine import Workspace
from bomstudio.native import Project,BASE
from bomstudio.writeback import compile_plan,apply_plan

class NativeFirst(Fixture):
 def setUp(self):
  super().setUp()
  self.env=patch.dict(os.environ,{'WAYRICAD_KICAD_CONFIG_DIR':str(self.dir/'cfg')});self.env.start();self.addCleanup(self.env.stop)
  self.preset={'name':'User chosen','fields_ordered':[{'name':'Reference','label':'Designators','show':True,'group_by':False},{'name':'MPN','label':'Order code','show':True,'group_by':True},{'name':'Value','label':'Hidden value','show':False,'group_by':True}], 'sort_field':'MPN','sort_asc':False,'group_symbols':True,'exclude_dnp':True,'include_excluded_from_bom':False,'filter_string':'R*'}
  self.ws.project.pro.setdefault('schematic',{}).update(bom_settings=deepcopy(self.preset),bom_fmt_settings=dict(nf.FORMAT,field_delimiter=';',string_delimiter="'",ref_delimiter=' / ',ref_range_delimiter='~'))
 def global_fields(self,text):
  p=self.dir/'cfg';p.mkdir(exist_ok=True);(p/'eeschema.json').write_text(json.dumps({'drawing':{'field_names':text}}))
 def test_default_is_native(self):self.assertEqual(nf.preferences(self.ws)['mode'],'native')
 def test_hidden_and_unmentioned_columns_stay_hidden(self):self.assertEqual(fr.inventory(self.ws)['default_columns'],['@field:Reference','@field:MPN'])
 def test_original_labels_and_sort(self):
  c=nf.context(self.ws);self.assertEqual(c['view']['labels']['@field:MPN'],'Order code');self.assertFalse(c['view']['sort_asc'])
 def test_actual_fields_remain_discoverable(self):self.assertIn('@field:Footprint',[f['key'] for f in fr.inventory(self.ws)['fields']])
 def test_legacy_view_not_activated_or_deleted(self):
  self.ws.state['view']={'columns':['Currency','UnitPrice']};d=self.ws.public();self.assertEqual(d['view']['columns'],['@field:Reference','@field:MPN']);self.assertEqual(self.ws.state['view']['columns'],['Currency','UnitPrice'])
 def test_global_native_sexpr(self):
  self.global_fields('(templatefields (field (name "Mass") visible) (field (name "Data") url))');x=nf.templates(self.ws)['global'];self.assertTrue(x[0]['visible']);self.assertFalse(x[0]['url']);self.assertTrue(x[1]['url'])
 def test_global_array_supported(self):
  self.global_fields([{'name':'Mass','visible':False,'url':False}]);self.assertEqual(nf.templates(self.ws)['global'][0]['name'],'Mass')
 def test_global_project_precedence(self):
  self.global_fields('(templatefields (field (name "Code") visible) (field (name "Mass")))');self.ws.project.pro['schematic']['drawing']={'field_names':[{'name':'Code','visible':False,'url':True}]};t=nf.templates(self.ws)['effective'];self.assertEqual([f['name'] for f in t],['Code','Mass']);self.assertEqual(t[0]['source'],'project');self.assertFalse(t[0]['visible'])
 def test_schematic_visibility_not_export_visibility(self):
  self.global_fields('(templatefields (field (name "Secret") visible))');self.assertNotIn('@field:Secret',fr.inventory(self.ws)['default_columns'])
 def test_absent_native_template_remains_absent(self):
  self.global_fields('(templatefields (field (name "Missing")))');self.assertIn('Missing',[f['name'] for f in fr.inventory(self.ws)['fields']]);self.assertNotIn('Missing',self.row('R1')['raw'])
 def test_bad_global_reports_warning(self):
  self.global_fields('(wrong)');self.assertTrue(nf.templates(self.ws)['warnings'])
 def test_global_cache_invalidates(self):
  self.global_fields('(templatefields (field (name "Mass")))');self.assertEqual(nf.templates(self.ws)['global'][0]['name'],'Mass');self.global_fields('(templatefields (field (name "Vendor")))');self.assertEqual(nf.templates(self.ws)['global'][0]['name'],'Vendor')
 def test_read_does_not_mutate(self):
  state=self.ws._serialize();pro=deepcopy(self.ws.project.pro);nf.context(self.ws);self.ws.public();fr.inventory(self.ws);self.assertEqual(state,self.ws._serialize());self.assertEqual(pro,self.ws.project.pro)
 def test_expressions_preserved_in_field_templates(self):
  self.global_fields('(templatefields (field (name "${REV}") visible))');self.assertEqual(nf.templates(self.ws)['effective'][0]['name'],'${REV}')
 def test_native_request_explicit_saved_values(self):
  c=nf.inherited_options(self.ws);self.assertEqual(c['fields'],['Reference','MPN']);self.assertEqual(c['labels'],['Designators','Order code']);self.assertEqual(c['field_delimiter'],';');self.assertEqual(c['string_delimiter'],"'");self.assertEqual(c['ref_range_delimiter'],'~');self.assertFalse(c['sort_asc'])
 def test_hidden_group_fields_preserved(self):self.assertEqual(nf.inherited_options(self.ws)['group_by'],['MPN','Value'])
 def test_no_native_grouping(self):self.ws.project.pro['schematic']['bom_settings']['group_symbols']=False;self.assertEqual(nf.inherited_options(self.ws)['group_by'],[])
 def test_empty_visible_stays_empty(self):
  for f in self.ws.project.pro['schematic']['bom_settings']['fields_ordered']:f['show']=False
  self.assertEqual(fr.inventory(self.ws)['default_columns'],[])
  with self.assertRaisesRegex(ValueError,'no visible'):nf.inherited_options(self.ws)
 def test_missing_preset_fails_not_silent_fallback(self):
  with self.assertRaisesRegex(ValueError,'no longer exists'):nf.select(self.ws,preset='99')
  self.assertEqual(nf.preferences(self.ws)['preset'],'@current')
 def test_named_presets_preserve_comma_names(self):
  self.ws.project.pro['schematic']['bom_presets']=[deepcopy(self.preset)];nf.select(self.ws,preset='0');c=nf.inherited_options(self.ws);self.assertEqual(c['preset'],'User chosen');self.assertNotIn('fields',c)
 def test_named_format_uses_preset(self):
  self.ws.project.pro['schematic']['bom_fmt_presets']=[dict(nf.FORMAT,name='Format 1')];nf.select(self.ws,format_preset='0');c=nf.inherited_options(self.ws);self.assertEqual(c['format_preset'],'Format 1');self.assertNotIn('field_delimiter',c)
 def test_current_comma_field_refused_by_cli_encoding(self):
  self.ws.project.pro['schematic']['bom_settings']['fields_ordered'][0]['name']='A,B';config=nf.inherited_options(self.ws)
  with self.assertRaisesRegex(ValueError,'commas'):nativebom.arguments(config,{'options':['--'+k.replace('_','-') for k in config],'help':'--sort-asc VAR'})
 def test_native_copy_does_not_enforce(self):
  old=deepcopy(self.ws.project.pro);fields=deepcopy(self.row('R1')['raw']);x=nf.customize(self.ws,'Mine');self.assertEqual(x['template']['columns'][2]['export'],False);self.assertTrue(x['warnings']);self.assertEqual(self.row('R1')['raw'],fields);self.assertEqual(old,self.ws.project.pro)
 def test_custom_template_duplicate_refused(self):
  nf.customize(self.ws,'Mine')
  with self.assertRaisesRegex(ValueError,'already exists'):nf.customize(self.ws,'Mine')
 def test_return_native_retains_copy(self):
  nf.customize(self.ws,'Mine');nf.select(self.ws,'native');self.assertIn('Mine',self.ws.state['templates']);self.assertEqual(nf.preferences(self.ws)['mode'],'native')
 def test_customization_undo(self):
  nf.customize(self.ws,'Mine');self.ws.undo();self.assertNotIn('Mine',self.ws.state['templates']);self.assertEqual(nf.preferences(self.ws)['mode'],'native')
 def test_merge_preserves_custom_labels(self):
  nf.customize(self.ws,'Mine');self.ws.state['templates']['Mine']['columns'][0]['label']='Custom ref';self.ws.state['templates']['Mine']['columns'].pop(1);nf.customize(self.ws,'Mine',True);self.assertEqual(self.ws.state['templates']['Mine']['columns'][0]['label'],'Custom ref');self.assertEqual(self.ws.state['templates']['Mine']['columns'][-1]['field'],'@field:MPN')
 def test_reverse_preview_readonly(self):
  nf.customize(self.ws,'Mine');state=self.ws._serialize();p=nf.reverse_preview(self.ws,'Mine');self.assertIn('bom_settings',p['settings']);self.assertEqual(state,self.ws._serialize())
 def test_reverse_requires_confirmation(self):
  nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine')
  for token,ack in [('APPLY',True),('FORMAT',False)]:
   with self.subTest(token=token,ack=ack),self.assertRaises(ValueError):nf.reverse_apply(self.ws,'Mine',p['fingerprint'],token,ack)
 def test_reverse_stales_on_field_change(self):
  nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine');self.edit('R1',{'Value':'47k'})
  with self.assertRaisesRegex(ValueError,'stale'):nf.reverse_apply(self.ws,'Mine',p['fingerprint'],'FORMAT',True)
 def test_reverse_stales_on_global_change(self):
  self.global_fields('(templatefields)');nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine');self.global_fields('(templatefields (field (name "new")))')
  with self.assertRaisesRegex(ValueError,'stale'):nf.reverse_apply(self.ws,'Mine',p['fingerprint'],'FORMAT',True)
 def test_reverse_stage_does_not_write(self):
  original=self.path.read_bytes();nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine');nf.reverse_apply(self.ws,'Mine',p['fingerprint'],'FORMAT',True);self.assertEqual(original,self.path.read_bytes());self.assertIsNotNone(self.ws.state['native_bom_settings'])
 def test_reverse_roundtrip_and_variables_preserved(self):
  # Persist the fixture's chosen native settings before using actual writeback.
  self.path.write_text(json.dumps(self.ws.project.pro));self.ws=Workspace(Project(self.path));before_sch=self.ws.project.root.read_bytes();variables=deepcopy(self.ws.project.variables)
  nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine');nf.reverse_apply(self.ws,'Mine',p['fingerprint'],'FORMAT',True)
  plan=compile_plan(self.ws);self.ws,backup=apply_plan(self.ws,plan['fingerprint'],'APPLY',True)
  self.assertEqual(self.ws.project.root.read_bytes(),before_sch);self.assertEqual(self.ws.project.variables,variables);self.assertIsNone(self.ws.state['native_bom_settings']);self.assertEqual(self.ws.project.pro['schematic']['bom_settings'],p['settings']['bom_settings']);self.assertTrue(Path(backup).is_dir())
 def test_reverse_does_not_change_global_templates(self):
  self.global_fields('(templatefields (field (name "Immutable")))');g=(self.dir/'cfg/eeschema.json').read_bytes();nf.customize(self.ws,'Mine');p=nf.reverse_preview(self.ws,'Mine');nf.reverse_apply(self.ws,'Mine',p['fingerprint'],'FORMAT',True);self.assertEqual(g,(self.dir/'cfg/eeschema.json').read_bytes())
 def test_reverse_alias_or_computed_refused(self):
  nf.customize(self.ws,'Mine');self.ws.state['templates']['Mine']['columns'].append({'field':'OrderCost','label':'Price'})
  with self.assertRaisesRegex(ValueError,'no native source'):nf.reverse_preview(self.ws,'Mine')
 def test_reverse_inclusion_polarity_not_guessed(self):
  nf.customize(self.ws,'Mine');self.ws.state['templates']['Mine']['columns'].append({'field':'InBOM','label':'Included'})
  with self.assertRaisesRegex(ValueError,'inverted'):nf.reverse_preview(self.ws,'Mine')
 def test_invalid_authority_rejected(self):
  self.ws.state['bom_preferences']={'mode':'automatic-enforce'}
  with self.assertRaises(ValueError):self.ws._validate_state()
 def test_custom_schema_reload(self):
  nf.customize(self.ws,'Mine');self.ws.save();w=Workspace(Project(self.path));self.assertEqual(nf.preferences(w)['custom_template'],'Mine')
 def test_state_preserves_legacy_fields(self):
  nf.select(self.ws,'native');self.ws.save();w=Workspace(Project(self.path));self.assertEqual(set(w.state['templates']),set(self.ws.state['templates']))
 def test_unknown_scope_not_guessed(self):
  self.ws.project.pro['schematic']['bom_settings']['filter_scope']='current_sheet'
  with self.assertRaisesRegex(ValueError,'scope'):nf.inherited_options(self.ws)
 def test_no_saved_config_uses_native_field_order(self):
  self.ws.project.pro['schematic'].pop('bom_settings');x=nf.context(self.ws);self.assertEqual(x['preset']['name'],'Default Editing');self.assertEqual(x['view']['columns'][:3],['@field:Reference','Qty','@field:Value'])
 def test_invalid_native_boolean_refused(self):
  p={'bom_settings':deepcopy(self.preset),'bom_fmt_settings':nf.FORMAT};p['bom_settings']['exclude_dnp']='no'
  with self.assertRaises(ValueError):nf.validate_native(p)
 def test_unsafe_native_key_refused(self):
  with self.assertRaises(ValueError):nf.validate_native({'bom_settings':self.preset,'bom_fmt_settings':dict(nf.FORMAT,execute='bad')})
 def test_invalid_current_preset_not_coerced(self):
  self.ws.project.pro['schematic']['bom_settings']['fields_ordered'][0]['show']='false'
  with self.assertRaises(ValueError):nf.context(self.ws)
 def test_desktop_entrypoint_in_manifest(self):
  root=Path(__file__).resolve().parents[1];j=json.loads((root/'plugin.json').read_text());self.assertEqual(j['actions'][0]['entrypoint'],'desktop_entrypoint.py');self.assertTrue((root/'desktop_entrypoint.py').is_file())
 def test_desktop_entrypoint_rejects_browser(self):
  import desktop_entrypoint
  with patch('sys.argv',['desktop_entrypoint.py','--ui','browser']),self.assertRaises(SystemExit):desktop_entrypoint.desktop_main()
 def test_desktop_entrypoint_forces_desktop(self):
  import desktop_entrypoint
  with patch('sys.path',[str(Path(__file__).resolve().parents[2]),*os.sys.path]),patch('sys.argv',['desktop_entrypoint.py']),patch('wayricad_runtime.bootstrap.relaunch',return_value=None),patch.object(desktop_entrypoint,'main',return_value=0) as m:
   self.assertEqual(desktop_entrypoint.desktop_main(),0);self.assertEqual(os.sys.argv[-2:],['--ui','desktop'])
 def test_runtime_diagnostic_no_changes(self):
  from bomstudio.runtime_info import diagnostic
  d=diagnostic(roots=[self.dir]);self.assertTrue(d['read_only']);self.assertEqual(d['runtime']['version'],json.loads((Path(__file__).resolve().parents[1]/'metadata.json').read_text(encoding='utf-8'))['versions'][0]['version']);self.assertNotIn('token',d['runtime'])
 def test_duplicate_manifest_detected(self):
  from bomstudio.runtime_info import diagnostic
  for n in ('a','b'):
   p=self.dir/n;p.mkdir();(p/'plugin.json').write_text(json.dumps({'identifier':'org.wayricad.bomstudio','actions':[{'entrypoint':'entrypoint.py'}]}))
  self.assertEqual(len(diagnostic(roots=[self.dir])['installations']),2)
 def test_cli_format_commands_registered(self):
  self.assertEqual(cli.parser().parse_args(['bom-format','show',str(self.path)]).operation,'show')
