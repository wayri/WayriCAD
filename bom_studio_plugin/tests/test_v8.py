"""0.8 field, finder, native-library and desktop contracts; not KiCad-host tests."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import base64, copy, gzip, hashlib, http.client, io, json, shutil, tempfile, threading, unittest
from test_core import Fixture
from bomstudio import field_registry, classification, catalogbrowse, partsdb, librarymaker, nativebom, desktop, bulkedit
from bomstudio.native import BASE
from bomstudio.server import Application,Server
from bomstudio.sexpr import parse

class Fields8(Fixture):
 def add(self,fields):
  self.ws.project.by_id[self.row('R1')['id']].fields.update(fields)
 def test_actual_names_are_initial_columns(self):
  self.add({'Vendor Part Code':'A','Board Role':'power'})
  x=field_registry.inventory(self.ws);self.assertIn('@field:Vendor Part Code',x['default_columns']);self.assertIn('@field:Board Role',x['default_columns'])
 def test_blank_is_not_currency_default(self):
  self.add({'Currency':'','Source':'authored','Qty':'777','Assembly':'custom label'})
  r=self.row('R1');self.assertEqual(r['fields']['@field:Currency'],'');self.assertEqual(r['fields']['@field:Qty'],'777');self.assertEqual(r['fields']['Qty'],1);self.assertEqual(r['fields']['@field:Source'],'authored')
 def test_blank_alias_distinct(self):
  self.add({'MPN':'','Custom MPN':'EXACT'});self.ws.set_aliases({'MPN':['Custom MPN']})
  r=self.row('R1');self.assertEqual(r['fields']['@field:MPN'],'');self.assertEqual(r['fields']['MPN'],'EXACT')
 def test_alias_conflict_is_explicit(self):
  self.add({'MPN':'A','Custom MPN':'B'});self.ws.set_aliases({'MPN':['Custom MPN']})
  self.assertTrue(self.row('R1')['alias_conflicts']);self.assertTrue(any(i['code']=='ALIAS_CONFLICT' for i in self.ws.checks()))
 def test_custom_qty_edit_not_computed_edit(self):
  self.add({'Qty':'777'});entries=[{'ids':[self.row('R1')['id']],'changes':{'@field:Qty':'12'}}]
  p=bulkedit.preview(self.ws,BASE,entries);bulkedit.apply(self.ws,BASE,entries,p['fingerprint'],'EDIT')
  self.assertEqual(self.row('R1')['fields']['@field:Qty'],'12');self.assertEqual(self.row('R1')['fields']['Qty'],1)
 def test_custom_source_edit(self):
  self.add({'Source':'old'});e=[{'ids':[self.row('R1')['id']],'changes':{'@field:Source':'new'}}];p=bulkedit.preview(self.ws,BASE,e);bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'EDIT');self.assertEqual(self.row('R1')['raw']['Source'],'new')
 def test_reference_not_editable(self):
  with self.assertRaises(ValueError):bulkedit.preview(self.ws,BASE,[{'ids':[self.row('R1')['id']],'changes':{'@field:Reference':'R2'}}])
 def test_unknown_exact_field_rejected(self):
  with self.assertRaises(ValueError):bulkedit.normalize_changes(self.row('R1'),{'@field:does-not-exist':'x'})
 def test_attribute_inversion(self):
  e=[{'ids':[self.row('R1')['id']],'changes':{'@attribute:exclude_bom':True}}];p=bulkedit.preview(self.ws,BASE,e);bulkedit.apply(self.ws,BASE,e,p['fingerprint'],'EDIT');self.assertFalse(self.row('R1')['flags']['in_bom'])
 def test_attribute_string_is_not_bool(self):
  with self.assertRaises(ValueError):bulkedit.normalize_changes(self.row('R1'),{'@attribute:exclude_bom':'false'})
 def test_variable_remains_raw(self):
  self.ws.set_variables('project',{'RV':'47k'});self.edit('R1',{'Value':'${RV}'})
  r=self.row('R1');self.assertEqual(r['raw']['Value'],'${RV}');self.assertEqual(r['fields']['@field:Value'],'47k')
 def test_counts_include_blank_and_absent(self):
  self.add({'EmptyCustom':''});x=next(f for f in field_registry.inventory(self.ws)['fields'] if f['name']=='EmptyCustom');self.assertEqual((x['present'],x['blank'],x['nonempty']),(1,1,0));self.assertEqual(x['missing'],len(self.ws.rows())-1)
 def test_native_label_order_not_field_rename(self):
  self.ws.project.pro['schematic']['bom_settings']={'fields_ordered':[{'name':'Value','label':'Comment','show':True,'group_by':True},{'name':'Footprint','label':'Package','show':False,'group_by':False}]}
  x=field_registry.inventory(self.ws);self.assertEqual(x['default_columns'][0],'@field:Value');self.assertEqual(x['labels']['@field:Value'],'Comment');self.assertNotIn('@field:Footprint',x['default_columns']);self.assertIn('Footprint',self.row('R1')['raw'])
 def test_adopt_does_not_modify_components(self):
  before=[r['raw'] for r in self.ws.rows()];field_registry.adopt(self.ws,BASE,all_fields=True);self.assertEqual(before,[r['raw'] for r in self.ws.rows()]);self.assertTrue(self.ws.state['view']['columns'])

 def test_exact_temperature_uses_configured_units(self):
  from bomstudio import analytics
  self.add({'Temp_Max':'75 C'});analytics.configure(self.ws,{'temperature_field':'Temp_Max','temperature_unit':'C'})
  r=analytics.threshold(self.ws,BASE,'@field:Temp_Max','<80');self.assertIn('R1',r['references']);self.assertEqual(r['canonical_unit'],'C')
 def test_exact_temperature_query_uses_configured_units(self):
  from bomstudio import analytics,search
  self.add({'Temp_Max':'75 C'});analytics.configure(self.ws,{'temperature_field':'Temp_Max','temperature_unit':'C'})
  rows,_=search.select(self.ws,BASE,'"@field:Temp_Max"<80');self.assertIn('R1',[r['ref'] for r in rows])
 def test_same_physical_field_conflicting_units_rejected(self):
  from bomstudio import analytics
  with self.assertRaises(ValueError):analytics.validate_config({'temperature_field':'Temp_Max','temperature_unit':'C','field_units':{'@field:Temp_Max':'F'}})

class Category8(unittest.TestCase):
 def c(self,ref='',**f):return classification.classify({'fields':f,'reference_hint':ref})
 def test_reference_R(self):self.assertEqual(self.c('R17')['category'],'Passives/Resistors')
 def test_reference_C(self):self.assertEqual(self.c('C5')['category'],'Passives/Capacitors')
 def test_U_not_guessed_mcu(self):self.assertEqual(self.c('U2')['category'],'Integrated circuits')
 def test_description_narrows_U(self):self.assertIn('Linear regulators',self.c('U2',Description='Low dropout LDO regulator')['category'])
 def test_keyword_capacitor(self):self.assertIn('Ceramic',self.c('C2',Keywords='MLCC X7R')['category'])
 def test_override_priority(self):self.assertEqual(self.c('R5',Category='Company/Flight qualified',Description='resistor')['category'],'Company/Flight qualified')
 def test_input_unchanged(self):
  p={'fields':{'Description':'MLCC capacitor'},'reference_hint':'C1'};before=copy.deepcopy(p);classification.classify(p);self.assertEqual(p,before)
 def test_conflict_not_hidden(self):
  c=self.c('R1',Description='ceramic capacitor');self.assertTrue(c['warnings'])
 def test_unclassified(self):self.assertEqual(self.c()['category'],'Unclassified')

class Finder8(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.lib=partsdb.Library(Path(self.tmp.name)/'catalogue',True)
  self.ids=[]
  for i in range(70):
   fields={'MPN':f'P{i:03}','Manufacturer':'MakerA' if i<50 else 'MakerB','Value':'10k' if i<50 else '100n','Footprint':'Demo:R' if i<50 else 'Demo:C','Description':'chip resistor' if i<50 else 'ceramic capacitor','Temp_Max':str(50+i)}
   pid=partsdb.record_identity(fields);p={'id':pid,'kind':'orderable','internal_pn':'IPN-'+str(i),'fields':fields,'reference_hint':'R1' if i<50 else 'C1','sources':[],'assets':[],'conflicts':[],'evidence':[],'status':'candidate','tags':[]}
   with self.lib.transaction():self.lib.put(p,'test','synthetic')
   self.ids.append(pid)
 def tearDown(self):self.lib.close();self.tmp.cleanup()
 def test_pagination_loads_page_only(self):
  r=catalogbrowse.search(self.lib,limit=10,summary=True);self.assertEqual((r['total'],r['records_loaded'],r['next_offset']),(70,10,10));self.assertNotIn('sources',r['items'][0])
 def test_warm_index(self):
  catalogbrowse.search(self.lib);r=catalogbrowse.search(self.lib);self.assertEqual(r['index']['updated_records'],0)
 def test_revision_refresh(self):
  catalogbrowse.search(self.lib);p=self.lib.get(self.ids[0]);p['fields']['Category']='Custom/One'
  with self.lib.transaction():self.lib.put(p,'test','new category')
  r=catalogbrowse.search(self.lib,category='Custom');self.assertEqual(r['total'],1);self.assertEqual(r['index']['updated_records'],1)
 def test_category_before_pagination(self):
  r=catalogbrowse.search(self.lib,category='Passives/Capacitors',limit=5);self.assertEqual(r['total'],20);self.assertEqual(len(r['items']),5)
 def test_manufacturer_filter(self):self.assertEqual(catalogbrowse.search(self.lib,manufacturer='MakerB')['total'],20)
 def test_numeric_filter(self):
  r=catalogbrowse.search(self.lib,filters=[{'field':'Temp_Max','op':'<','value':'80','unit':'C'}]);self.assertEqual(r['total'],30)
 def test_bad_sort_rejected(self):
  with self.assertRaises(ValueError):catalogbrowse.search(self.lib,sort='x;DROP TABLE parts')
 def test_search_does_not_change_epoch(self):
  old=self.lib.meta('epoch');catalogbrowse.search(self.lib);self.assertEqual(old,self.lib.meta('epoch'));self.assertTrue(self.lib.verify()['ok'])
 def test_fulltext_mpns(self):self.assertEqual(catalogbrowse.search(self.lib,query='P005')['total'],1)

class LibraryMaker8(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import os
  cls.config=tempfile.TemporaryDirectory()
  isolated={k:v for k,v in os.environ.items() if not k.upper().startswith('KICAD') and k.upper() not in ('PROGRAMFILES','PROGRAMFILES(X86)','APPDATA','XDG_CONFIG_HOME')}
  isolated.update(APPDATA=cls.config.name,XDG_CONFIG_HOME=cls.config.name)
  cls.environment=patch.dict(os.environ,isolated,clear=True);cls.environment.start()
  cls.app=Application(engineering_demo=True);cls.root=cls.app.demo_directory;cls.catalogue=cls.app.library_path
  r=next(r for r in cls.app.workspace.rows() if r['ref']=='R1');cls.pid=partsdb.record_identity(r['fields'])
 @classmethod
 def tearDownClass(cls):cls.app.link.close();shutil.rmtree(cls.root,ignore_errors=True);cls.environment.stop();cls.config.cleanup()
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.target=Path(self.tmp.name)/'UserParts'
 def tearDown(self):self.tmp.cleanup()
 def req(self,mode='empty',**extra):return dict(mode=mode,destination=str(self.target),name='UserParts',**extra)
 def test_empty_preview_no_destination(self):
  r=librarymaker.preview(self.req());self.assertFalse(self.target.exists());self.assertEqual(r['counts']['symbols'],0)
 def test_empty_creates_valid_native_containers_and_catalogue(self):
  r=librarymaker.apply(librarymaker.preview(self.req()),'CREATE');self.assertTrue(Path(r['symbol_library']).is_file());self.assertEqual(parse(Path(r['symbol_library']).read_text()).tag,'kicad_symbol_lib');self.assertTrue(Path(r['footprint_library']).is_dir());self.assertTrue(Path(r['catalogue_path'],'catalog.sqlite3').is_file())
 def test_existing_target_not_overwritten(self):
  self.target.mkdir();f=self.target/'keep.txt';f.write_text('preserve')
  with self.assertRaises(FileExistsError):librarymaker.preview(self.req())
  self.assertEqual(f.read_text(),'preserve')
 def test_target_created_after_review_blocks_apply(self):
  p=librarymaker.preview(self.req());self.target.mkdir()
  with self.assertRaises(FileExistsError):librarymaker.apply(p,'CREATE')
 def test_named_model_and_footprint_links(self):
  p=librarymaker.preview(self.req('catalogue',library=self.catalogue,ids=[self.pid]));r=librarymaker.apply(p,'CREATE')
  self.assertEqual(r['counts']['models'],2);text=Path(r['symbol_library']).read_text();self.assertIn('UserParts:KW_',text)
  fp=next(Path(r['footprint_library']).glob('*.kicad_mod')).read_text();self.assertIn((self.target/'UserParts.3dshapes').as_posix(),fp)
 def test_original_models_byte_identical(self):
  r=librarymaker.apply(librarymaker.preview(self.req('catalogue',library=self.catalogue,ids=[self.pid])),'CREATE')
  with partsdb.Library(self.catalogue) as lib:
   for p in Path(r['model_directory']).iterdir():self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),p.stem)
 def test_automatic_catalogue_for_projects(self):
  p=librarymaker.preview(self.req('projects',projects=[str(self.app.workspace.project.pro_path)],require_complete=False));self.assertTrue(p['new_catalogue']);self.assertGreater(p['counts']['symbols'],0)
  r=librarymaker.apply(p,'CREATE')
  with partsdb.Library(r['catalogue_path']) as lib:self.assertTrue(lib.verify()['ok']);self.assertGreater(lib.info()['parts'],0)
 def test_partial_sources_need_explicit_choice(self):
  with self.assertRaises(ValueError):librarymaker.preview(self.req('projects',projects=[str(self.app.workspace.project.pro_path)]))
 def test_stale_request_rejected(self):
  p=librarymaker.preview(self.req());p['request']['name']='Changed'
  with self.assertRaisesRegex(ValueError,'changed'):librarymaker.apply(p,'CREATE')
  self.assertFalse(self.target.exists())
 def test_confirmation_required(self):
  with self.assertRaisesRegex(ValueError,'CREATE'):librarymaker.apply(librarymaker.preview(self.req()),'YES')
 def test_publish_ordinary_failure_rolls_back(self):
  p=librarymaker.preview(self.req())
  with patch('bomstudio.librarymaker.shutil.copyfileobj',side_effect=OSError('simulated copy failure')):
   with self.assertRaises(OSError):librarymaker.apply(p,'CREATE')
  self.assertFalse(self.target.exists())
 def test_library_tables_only_snippets(self):
  librarymaker.apply(librarymaker.preview(self.req()),'CREATE');self.assertFalse((self.target/'sym-lib-table').exists());self.assertTrue((self.target/'table-snippets'/'sym-lib-table').exists());self.assertIn('(name "UserParts")',(self.target/'table-snippets'/'sym-lib-table').read_text())
 def test_path_traversal_rejected(self):
  with self.assertRaises(ValueError):librarymaker.preview({**self.req(),'destination':str(Path(self.tmp.name)/'..'/'new8')})
 def test_reserved_name_rejected(self):
  with self.assertRaises(ValueError):librarymaker.validate_request({**self.req(),'name':'NUL'})
 def test_unknown_option_rejected(self):
  with self.assertRaises(ValueError):librarymaker.preview({**self.req(),'execute':'shell'})
 def test_cancel_before_capture(self):
  with self.assertRaises(InterruptedError):librarymaker.preview(self.req(),cancel=lambda:True)
  self.assertFalse(self.target.exists())

class NativeBOM8(Fixture):
 def test_requires_saved_acknowledgement(self):
  with self.assertRaisesRegex(ValueError,'Acknowledge'):nativebom.generate(self.ws)
 def test_unknown_option_rejected(self):
  with self.assertRaises(ValueError):nativebom.arguments({'shell':'x'},{'options':[]})
 def test_no_flag_guessing(self):
  with self.assertRaisesRegex(ValueError,'advertise'):nativebom.arguments({'variant':'V'},{'options':[]})
 def test_argument_no_shell_interpretation(self):
  x=nativebom.arguments({'filter':'R*; not a shell','fields':['Reference','Value']},{'options':['--filter','--fields']});self.assertEqual(x,['--filter','R*; not a shell','--fields','Reference,Value'])
 def test_unavailable_explicit(self):
  with patch('bomstudio.nativebom.cli_path',return_value=None):self.assertFalse(nativebom.status()['available'])
 def test_version_subcommand_probe(self):
  def run(cmd,timeout=20):
   if cmd==['test-native-cli','version']:return SimpleNamespace(returncode=0,stdout='10.0.5',stderr='')
   if cmd==['test-native-cli','sch','export','bom','--help']:return SimpleNamespace(returncode=0,stdout='--fields VAR --variant VAR',stderr='')
   self.fail('Unsupported native command: '+repr(cmd))
  with patch('bomstudio.nativebom.cli_path',return_value='test-native-cli'),patch('bomstudio.nativebom._run',side_effect=run):
   r=nativebom.status();self.assertTrue(r['available']);self.assertEqual(r['version'],'10.0.5')
 def test_default_variant_no_capability_required(self):
  for value in ('',BASE):self.assertEqual(nativebom.arguments({'variant':value},{'options':[]}),[])
 def test_false_switch_no_capability_required(self):
  self.assertEqual(nativebom.arguments({'keep_tabs':False},{'options':[]}),[])
 def test_sort_parameter_true_false(self):
  for value in (True,False):self.assertEqual(nativebom.arguments({'sort_asc':value},{'options':['--sort-asc'],'help':'--sort-asc VAR'}),['--sort-asc',str(value).lower()])
 def test_compat_version_subcommand(self):
  from bomstudio import compat
  with patch('bomstudio.compat.cli_path',return_value='test-native-cli'),patch('bomstudio.compat.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='10.0.5 --variant',stderr='')) as run:
   compat.capabilities();self.assertEqual(run.call_args_list[0].args[0],['test-native-cli','version'])
 def test_success_bytes_not_reinterpreted(self):
  def run(cmd,timeout=20):
   Path(cmd[cmd.index('--output')+1]).write_bytes(b'"Vendor name","Value"\r\n"EXACT","${KEEP}"\r\n');return SimpleNamespace(returncode=0,stdout='',stderr='')
  with patch('bomstudio.nativebom.status',return_value={'available':True,'executable':'test-native-cli','options':[],'version':'10.test'}),patch('bomstudio.nativebom._run',side_effect=run):
   r=nativebom.generate(self.ws,{},True);self.assertIn(b'${KEEP}',r['data']);self.assertIn(b'\r\n',r['data'])

class Desktop8(unittest.TestCase):
 def test_default_is_desktop(self):self.assertEqual(desktop.ui_mode(),'desktop')
 def test_browser_requires_explicit_option(self):self.assertEqual(desktop.ui_mode(ui='browser'),'browser')
 def test_no_browser_is_headless(self):self.assertEqual(desktop.ui_mode(True),'none')
 def test_conflicting_modes_rejected(self):
  with self.assertRaises(ValueError):desktop.ui_mode(True,'browser')
 def test_bad_names_rejected(self):
  for name in ('../secret','A/B','NUL.txt','x:stream','bad\0name'):
   with self.subTest(name=name),self.assertRaises(ValueError):desktop._filename(name)
 def test_external_scripts_rejected(self):
  for u in ('javascript:alert(1)','file:///etc/passwd','https://user:pass@example.com'):
   with self.subTest(url=u),self.assertRaises(ValueError):desktop._http_url(u)
 def test_unauthenticated_save_fails(self):
  server=SimpleNamespace(app=SimpleNamespace(token='secret'),origin='http://127.0.0.1:8000')
  api=desktop.DesktopAPI(server,SimpleNamespace());self.assertFalse(api.save_download('safe.csv',base64.b64encode(b'data').decode(),'wrong')['ok'])
 def test_native_save_new_file(self):
  with tempfile.TemporaryDirectory() as t:
   dest=Path(t)/'safe.csv';server=SimpleNamespace(app=SimpleNamespace(token='secret'),origin='http://127.0.0.1:8000');api=desktop.DesktopAPI(server,SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1)))
   api._window=SimpleNamespace(get_current_url=lambda:'http://127.0.0.1:8000/',create_file_dialog=lambda *a,**kw:str(dest))
   r=api.save_download('safe.csv',base64.b64encode(b'bytes').decode(),'secret');self.assertTrue(r['ok']);self.assertEqual(dest.read_bytes(),b'bytes')
   self.assertFalse(api.save_download('safe.csv',base64.b64encode(b'overwrite').decode(),'secret')['ok']);self.assertEqual(dest.read_bytes(),b'bytes')
 def test_native_save_rejects_changed_origin(self):
  server=SimpleNamespace(app=SimpleNamespace(token='secret'),origin='http://127.0.0.1:8000');api=desktop.DesktopAPI(server,SimpleNamespace());api._window=SimpleNamespace(get_current_url=lambda:'https://external.example/')
  self.assertFalse(api.save_download('safe.csv','YmI=','secret')['ok'])

if __name__=='__main__':unittest.main()

class Mapping8(unittest.TestCase):
 def test_protobuf_path_precedes_wrapper(self):
  from bomstudio.bridge import footprint_path_details
  u='11111111-1111-4111-8111-111111111111';p=SimpleNamespace(proto=SimpleNamespace(symbol_path=SimpleNamespace(path=[SimpleNamespace(value=u)])),sheet_path='broken')
  self.assertEqual(footprint_path_details(p)['path'],'/'+u)
 def test_invalid_native_path_does_not_fallback(self):
  from bomstudio.bridge import footprint_path_details
  p=SimpleNamespace(proto=SimpleNamespace(symbol_path=SimpleNamespace(path=[SimpleNamespace(value='bad')])),sheet_path='/11111111-1111-4111-8111-111111111111')
  self.assertEqual(footprint_path_details(p)['state'],'invalid')
 def test_kiids_wrapper_supported(self):
  from bomstudio.bridge import symbol_path
  u='11111111-1111-4111-8111-111111111111';self.assertEqual(symbol_path(SimpleNamespace(kiids=[u])),'/'+u)
 def test_debug_string_is_not_path(self):
  from bomstudio.bridge import path_details
  self.assertEqual(path_details('SheetPath{path:1111}')['state'],'invalid')
 def test_mapping_unconnected_no_claim(self):
  from bomstudio.bridge import Bridge
  r=Bridge().mapping_report();self.assertFalse(r['connected']);self.assertEqual(r['components'],[])
 def test_local_browser_fallback_on_absent_desktop(self):
  from bomstudio import desktop
  server=SimpleNamespace()
  with patch.object(desktop,'_run_embedded',side_effect=desktop.DesktopUnavailable('missing WebView')),patch.object(desktop,'run_local_browser') as fallback:
   desktop.run(server)
   fallback.assert_called_once_with(server,None,'missing WebView')
