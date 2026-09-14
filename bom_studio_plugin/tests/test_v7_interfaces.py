"""Asset browser CLI, HTTP, isolation and bounded-input regression tests."""
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch
import io,json,http.client,threading,unittest,zipfile,time
from test_v7 import WRL
from test_v6 import EngFixture
from bomstudio import assetbundle as a,assetpreview as p,meshpreview as m,nativepreview as n,partsdb,cli,engineering,automation
from bomstudio.server import Application,Server

class Interface(EngFixture):
 def setUp(self):
  super().setUp();fp=self.footprint();folder=self.dir/'models';folder.mkdir();self.model=folder/'body.wrl';self.model.write_bytes(WRL)
  fp.write_text(fp.read_text()[:-1]+' (model "${KIPRJMOD}/models/body.wrl"))');self.ws.save();plan=partsdb.harvest([str(self.path)]);partsdb.import_harvest(self.lib,plan,'IMPORT','Test author');self.pid=partsdb.record_identity(self.row('R1')['fields']);self.partdata=self.lib.get(self.pid);self.plan=plan
 def runcli(self,*args):
  out=io.StringIO();err=io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main(['catalog',*args])
  return code,json.loads((out.getvalue() or err.getvalue()).strip())
 def test_cli_assets_without_project(self):
  code,r=self.runcli('assets','--library',str(self.lib.root),'--id',self.pid);self.assertEqual(code,0);self.assertEqual(r['data']['schema'],'wayricad-asset-browser-1')
 def test_cli_svg(self):
  out=self.dir/'new.svg';code,r=self.runcli('preview','--library',str(self.lib.root),'--id',self.pid,'--kind','symbol','--format','svg','--output',str(out));self.assertEqual(code,0);self.assertIn('<svg',out.read_text())
 def test_cli_mesh_json(self):
  code,r=self.runcli('preview','--library',str(self.lib.root),'--id',self.pid,'--kind','model');self.assertEqual(code,0);self.assertGreater(r['data']['triangle_count'],0)
 def test_cli_download_original(self):
  out=self.dir/'body-export.wrl';code,r=self.runcli('asset-export','--library',str(self.lib.root),'--id',self.pid,'--hash',a.sha(WRL),'--output',str(out));self.assertEqual(code,0);self.assertEqual(out.read_bytes(),WRL)
 def test_cli_export_symbol_file(self):
  h=next(x['hash'] for x in self.partdata['assets'] if x['kind']=='symbol');out=self.dir/'Export.kicad_sym';code,r=self.runcli('asset-export','--library',str(self.lib.root),'--id',self.pid,'--hash',h,'--output',str(out));self.assertEqual(code,0);self.assertIn('(kicad_symbol_lib',out.read_text())
 def test_cli_export_footprint_file(self):
  h=next(x['hash'] for x in self.partdata['assets'] if x['kind']=='footprint');out=self.dir/'Export.kicad_mod';code,r=self.runcli('asset-export','--library',str(self.lib.root),'--id',self.pid,'--hash',h,'--output',str(out));self.assertEqual(code,0);self.assertIn('(footprint',out.read_text())
 def test_asset_export_never_overwrites(self):
  out=self.dir/'same.wrl';out.write_text('ORIGINAL');code,r=self.runcli('asset-export','--library',str(self.lib.root),'--id',self.pid,'--hash',a.sha(WRL),'--output',str(out));self.assertEqual(code,4);self.assertEqual(out.read_text(),'ORIGINAL')
 def test_asset_export_cannot_target_design(self):
  code,r=self.runcli('asset-export','--library',str(self.lib.root),'--id',self.pid,'--hash',a.sha(WRL),'--output',str(self.dir/'new.kicad_pcb'));self.assertEqual(code,2)
 def test_cli_filter_json(self):
  f=self.dir/'filter.json';f.write_text(json.dumps([{'field':'Value','op':'equals','value':'10k'}]));code,r=self.runcli('search','--library',str(self.lib.root),'--has-asset','all3','--filters',str(f));self.assertEqual(code,0);self.assertGreater(r['data']['total'],0)
 def test_cli_native_complete_export(self):
  out=self.dir/'parts.zip';code,r=self.runcli('native-export','--library',str(self.lib.root),'--ids',self.pid,'--require-complete','--output',str(out));self.assertEqual(code,0)
  with zipfile.ZipFile(out) as z:self.assertEqual(len([x for x in z.namelist() if x.startswith('WayriCAD.3dshapes/')]),1)
 def test_cli_harvest_idempotent_import(self):
  f=self.dir/'plan.json';f.write_text(json.dumps(self.plan));code,r=self.runcli('import','--library',str(self.lib.root),'--plan',str(f),'--confirm','IMPORT','--actor','Tester');self.assertEqual(code,0);self.assertEqual(r['data']['count'],0)
 def test_large_plan_reader_does_not_relax_normal_json(self):
  text=json.dumps({'schema':'wayricad-harvest-1','unused':'a'*(21*1024*1024)});f=self.dir/'large.json';f.write_text(text)
  with self.assertRaises(ValueError):automation.load_json(f)
  self.assertEqual(a.read_harvest_plan(str(f))['schema'],'wayricad-harvest-1')
 def test_large_plan_reader_rejects_duplicate_keys(self):
  f=self.dir/'bad.json';f.write_text('{"schema":"wayricad-harvest-1","schema":"wayricad-harvest-1"}')
  with self.assertRaises(ValueError):a.read_harvest_plan(str(f))
 def test_dedicated_native_export_does_not_weaken_other_outputs(self):
  with self.assertRaises(ValueError):automation.write_new(self.dir/'new.kicad_sym',b'not allowed')
 def test_http_catalog_preview_no_project(self):
  app=Application();app.workspace=None;app.library_path=str(self.lib.root);server=Server(app);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
  def call(op,data,token=True):
   c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('POST','/api/engineering/'+op,json.dumps(data),{'Content-Type':'application/json',**({'X-Bom-Token':app.token} if token else {})});r=c.getresponse();ret=(r.status,r.read());c.close();return ret
  try:
   code,raw=call('assets',{'id':self.pid});self.assertEqual(code,200);self.assertEqual(json.loads(raw)['part_id'],self.pid)
   code,raw=call('preview',{'id':self.pid,'kind':'footprint'});self.assertEqual(code,200);self.assertIn('<svg',json.loads(raw)['svg'])
   code,raw=call('asset-download',{'id':self.pid,'hash':a.sha(WRL)});self.assertEqual(code,200);self.assertEqual(raw,WRL)
   self.assertEqual(call('assets',{'id':self.pid},False)[0],401)
   self.assertEqual(call('asset-download',{'id':self.pid,'hash':'0'*64})[0],400)
  finally:server.shutdown();server.server_close();t.join(2)
 def test_http_task_worker_read_only(self):
  app=SimpleNamespace(workspace=None,library_path=str(self.lib.root));before=self.lib.meta('epoch');task=engineering.dispatch(app,'preview-start',{'id':self.pid,'kind':'model'});start=time.monotonic()
  while True:
   result=engineering.dispatch(app,'task-status',{'id':task['id'],'include_result':True})
   if result['state'] in ('ready','failed','canceled'):break
   if time.monotonic()-start>15:raise AssertionError('Preview task timeout')
   time.sleep(.05)
  self.assertEqual(result['state'],'ready');self.assertGreater(result['result']['triangle_count'],0);self.assertEqual(before,self.lib.meta('epoch'))
 def test_preview_no_project_files_or_write(self):
  before=self.lib.meta('epoch');self.model.unlink();r=p.preview(self.lib,self.pid,'model');self.assertIn('No original',r['source']);self.assertEqual(before,self.lib.meta('epoch'))

class EdgeCases(unittest.TestCase):
 def test_cancel_3d_before_parse(self):
  with self.assertRaises(InterruptedError):m.convert(WRL,'.wrl',lambda:True)
 def test_worker_parse_failure_does_not_render_box(self):
  with self.assertRaises(ValueError):m.convert(b'bad arbitrary text','.wrl')
 def test_external_texture_warns_dependency(self):
  self.assertTrue(a.model_dependency_warnings(b'#VRML V2.0 utf8\nShape { appearance Appearance { texture ImageTexture { url "missing.png" } }}','.wrl'))
 def test_external_step_warns_dependency(self):self.assertTrue(a.model_dependency_warnings(b'ISO-10303-21; #1=EXTERNAL_SOURCE(...)','.step'))
 def test_external_obj_warns_dependency(self):self.assertTrue(a.model_dependency_warnings(b'mtllib x.mtl\nv 0 0 0','.obj'))
 def test_standalone_model_no_external_dependency(self):self.assertEqual(a.model_dependency_warnings(WRL,'.wrl'),[])
 def test_positive_kicad_angle_rotates_counterclockwise_svg(self):
  r=n.svg_preview(b'(footprint "F" (layer "F.Cu") (pad "1" smd rect (at 0 0 30) (size 2 1) (layers "F.Cu")))','footprint');self.assertIn('rotate(-30 ',r['svg'])
 def test_invalid_coordinate_refuses_preview(self):
  with self.assertRaises(ValueError):n.svg_preview(b'(footprint "F" (fp_line (start nope 2) (end 0 0)))','footprint')
 def test_new_hidden_pin_syntax(self):
  r=n.svg_preview(b'(symbol "T" (symbol "T_1_1" (pin passive line (at 0 0 0) (length 1) (hide yes) (name "X") (number "1"))))','symbol');self.assertTrue(r['pins'][0]['hidden'])
 def test_independent_compiled_murmur_vectors(self):
  data=json.loads(Path(__file__).with_name('fixtures_v7_hashes.json').read_text())
  for v in data['vectors']:
   with self.subTest(length=v['length']):self.assertEqual(a.murmur128(bytes(i%251 for i in range(v['length']))),v['hash'])
 def test_preview_capability_report(self):
  self.assertTrue(p.capabilities()['offline'])

if __name__=='__main__':unittest.main()
