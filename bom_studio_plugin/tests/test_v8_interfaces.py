"""HTTP/CLI integration for the new creator and actual-field/finder contracts."""
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
from unittest.mock import patch
import gzip,http.client,io,json,tempfile,threading,time,unittest
from bomstudio import cli,partsdb
from bomstudio.server import Application,Server

class Interfaces8(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.app=Application(engineering_demo=True);cls.server=Server(cls.app);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.thread.join(3)
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def http(self,path,data=None,auth=True,headers=None,method=None):
  h={'Content-Type':'application/json',**({'X-Bom-Token':self.app.token} if auth else {}),**(headers or {})};c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=30)
  c.request(method or ('GET' if data is None else 'POST'),'/api/'+path,None if data is None else json.dumps(data),h);r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
 def callcli(self,*args):
  out=io.StringIO();err=io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main(list(args))
  return code,json.loads((out.getvalue() or err.getvalue()).strip())
 def request(self):return {'mode':'empty','destination':str(self.dir/'CreatedParts'),'name':'CreatedParts','actor':'Automated test'}
 def test_inventory_http(self):
  code,_,b=self.http('fields/inventory',{});self.assertEqual(code,200);self.assertEqual(json.loads(b)['schema'],'wayricad-field-inventory-1')
 def test_inventory_auth(self):self.assertEqual(self.http('fields/inventory',{},False)[0],401)
 def test_compressed_state(self):
  code,h,b=self.http('state',headers={'Accept-Encoding':'gzip'});self.assertEqual(code,200);self.assertEqual(h.get('Content-Encoding'),'gzip');self.assertIn('field_inventory',json.loads(gzip.decompress(b)))
 def test_state_without_compression(self):
  code,h,b=self.http('state');self.assertEqual(code,200);self.assertNotIn('Content-Encoding',h);self.assertIn('rows',json.loads(b))
 def test_library_requires_auth(self):self.assertEqual(self.http('library/preview',{'request':self.request()},False)[0],401)
 def test_library_invalid_source_rejected(self):
  r=self.request();r['mode']='invalid';self.assertEqual(self.http('library/preview',{'request':r})[0],400);self.assertFalse(Path(r['destination']).exists())
 def test_library_http_review_apply(self):
  r=self.request();code,_,b=self.http('library/preview',{'request':r});self.assertEqual(code,200);plan=json.loads(b);self.assertFalse(Path(r['destination']).exists())
  code,_,b=self.http('library/apply',{'review_id':plan['review_id'],'confirmation':'CREATE','attach':False});self.assertEqual(code,200);self.assertTrue((Path(r['destination'])/'CreatedParts.kicad_sym').exists());self.assertEqual(json.loads(b)['counts']['symbols'],0)
 def test_library_wrong_confirmation(self):
  r=self.request();_,_,b=self.http('library/preview',{'request':r});plan=json.loads(b);self.assertEqual(self.http('library/apply',{'review_id':plan['review_id'],'confirmation':'WRONG'})[0],400);self.assertFalse(Path(r['destination']).exists())
 def test_async_library_preview(self):
  r=self.request();code,_,b=self.http('library/preview-start',{'request':r});self.assertEqual(code,200);task=json.loads(b)
  for _ in range(200):
   code,_,b=self.http('library/task-status',{'id':task['id']});result=json.loads(b)
   if result['state']!='running':break
   time.sleep(.02)
  self.assertEqual(result['state'],'ready');self.assertIn('review_id',result['result']);self.assertFalse(Path(r['destination']).exists())
 def test_finder_http_classification(self):
  code,_,b=self.http('engineering/search',{'summary':True,'category':'Passives','limit':2});self.assertEqual(code,200);r=json.loads(b);self.assertGreater(r['total'],0);self.assertLessEqual(len(r['items']),2);self.assertIn('classification',r['items'][0])
 def test_cli_fields(self):
  code,r=self.callcli('fields',str(self.app.workspace.project.pro_path));self.assertEqual(code,0);self.assertEqual(r['data']['schema'],'wayricad-field-inventory-1')
 def test_cli_create_preview_apply(self):
  source=self.dir/'request.json';source.write_text(json.dumps(self.request()));plan=self.dir/'review.json';code,r=self.callcli('library-create','preview','--request',str(source),'--output',str(plan));self.assertEqual(code,0)
  code,r=self.callcli('library-create','apply','--plan',str(plan),'--confirm','CREATE');self.assertEqual(code,0);self.assertTrue((self.dir/'CreatedParts'/'catalogue'/'catalog.sqlite3').is_file())
 def test_cli_missing_native_capability(self):
  with patch('bomstudio.nativebom.status',return_value={'available':False,'reason':'KiCad not installed'}):
   code,r=self.callcli('native-bom',str(self.app.workspace.project.pro_path),'--acknowledge-saved-only','--output',str(self.dir/'bom.csv'))
  self.assertEqual(code,6);self.assertFalse((self.dir/'bom.csv').exists())
 def test_cli_finder_category(self):
  code,r=self.callcli('catalog','search','--library',str(self.app.library_path),'--category','Passives','--sort','category','--summary');self.assertEqual(code,0);self.assertGreater(r['data']['total'],0);self.assertTrue(all(p['classification']['category'].startswith('Passives') for p in r['data']['items']))
 def test_cli_gui_mode_and_schema(self):
  a=cli.parser().parse_args(['gui','--ui','desktop']);self.assertEqual(a.ui,'desktop');code,r=self.callcli('schema');self.assertEqual(code,0);self.assertIn('library-create',str(r));self.assertEqual(len(cli.COMMANDS),39)
 def test_mapping_http_unconnected(self):
  code,_,b=self.http('link/mapping',{});self.assertEqual(code,200);self.assertEqual(json.loads(b)['schema'],'wayricad-link-mapping-1');self.assertFalse(json.loads(b)['connected'])
