"""CLI and HTTP regression contracts for native-first defaults; no KiCad host."""
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest.mock import patch
from copy import deepcopy
import http.client,io,json,threading,unittest
from test_core import Fixture
from bomstudio import cli,nativefirst as nf
from bomstudio.server import Application,Server
from bomstudio.engine import Workspace
from bomstudio.native import Project

class NativeFirstInterfaces(Fixture):
 def setUp(self):
  super().setUp();self.app=Application();self.app.workspace=self.ws;self.server=Server(self.app);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join(3);super().tearDown()
 def call(self,*args):
  out,err=io.StringIO(),io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main([str(x) for x in args])
  return code,out.getvalue(),err.getvalue()
 def request(self,path,body=None,auth=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10);h={'Content-Type':'application/json'}
  if auth:h['X-Bom-Token']=self.app.token
  c.request('GET' if body is None else 'POST','/api/'+path,body=None if body is None else json.dumps(body),headers=h);r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
 def test_http_native_mode_by_default(self):
  code,raw=self.request('state');d=json.loads(raw);self.assertEqual(code,200);self.assertEqual(d['bom_authority']['preferences']['mode'],'native');self.assertEqual(d['runtime']['version'],'3.0.0')
 def test_api_custom_preview_needs_template(self):self.assertEqual(self.request('export/preview',{})[0],400)
 def test_api_custom_export_needs_template(self):self.assertEqual(self.request('export',{})[0],400)
 def test_api_release_needs_template(self):self.assertEqual(self.request('release',{})[0],400)
 def test_api_native_export_requires_saved_ack(self):self.assertEqual(self.request('bom-format/export',{})[0],400)
 def test_runtime_auth_required(self):self.assertEqual(self.request('runtime/diagnostic',{},False)[0],401)
 def test_reverse_auth_required(self):self.assertEqual(self.request('bom-format/reverse-apply',{},False)[0],401)
 def test_customization_auth_required(self):self.assertEqual(self.request('bom-format/customize',{'name':'Mine'},False)[0],401);self.assertNotIn('Mine',self.ws.state['templates'])
 def test_http_reverse_stage_only(self):
  code,_=self.request('bom-format/customize',{'name':'Mine'});self.assertEqual(code,200)
  # Native default exclusions are expressions, not positive inclusion aliases.
  code,b=self.request('bom-format/reverse-preview',{'template':'Mine'});self.assertEqual(code,200,b);p=json.loads(b);original=self.path.read_bytes()
  code,b=self.request('bom-format/reverse-apply',{'template':'Mine','fingerprint':p['fingerprint'],'confirmation':'FORMAT','acknowledge':True});self.assertEqual(code,200,b);self.assertEqual(original,self.path.read_bytes());self.assertTrue(json.loads(b)['staged'])
 def test_cli_export_without_template_is_native(self):
  with patch('bomstudio.nativebom.generate',return_value={'data':b'native bytes\r\n','notice':'injected contract'}) as generate:
   code,_,err=self.call('export',self.path,'--format','csv','--acknowledge-saved-only','--output',self.dir/'native.csv')
  self.assertEqual(code,0,err);self.assertEqual((self.dir/'native.csv').read_bytes(),b'native bytes\r\n');self.assertIn('fields',generate.call_args.args[1]);self.assertTrue(generate.call_args.args[2])
 def test_cli_xlsx_requires_explicit_custom_template(self):
  code,_,_=self.call('export',self.path,'--format','xlsx','--output',self.dir/'bom.xlsx');self.assertEqual(code,2);self.assertFalse((self.dir/'bom.xlsx').exists())
 def test_cli_release_requires_explicit_template(self):
  with self.assertRaises(ValueError):cli.parser().parse_args(['release',str(self.path),'--output','release.zip'])
 def test_cli_authority_mutations_refuse_source_only(self):
  for op,args in [('follow',[]),('customize',['--template','Mine']),('merge',['--template','Mine']),('use-custom',['--template','Mine']),('apply',['--plan','plan.json','--confirm','FORMAT'])]:
   with self.subTest(op=op),self.assertRaises(ValueError):cli.parser().parse_args(['bom-format',op,str(self.path),'--source-only',*args])
 def test_cli_follow_preserves_saved_component_edits(self):
  self.edit('R1',{'Value':'22k'});self.ws.save();code,_,err=self.call('bom-format','follow',self.path);self.assertEqual(code,0,err);w=Workspace(Project(self.path));self.assertEqual(next(r for r in w.rows() if r['ref']=='R1')['raw']['Value'],'22k')
 def test_cli_native_no_config_inherits(self):
  with patch('bomstudio.nativebom.generate',return_value={'data':b'test','filename':'n.csv','command':[],'notice':'contract','version':'contract'}) as generate:
   code,_,err=self.call('native-bom',self.path,'--acknowledge-saved-only','--output',self.dir/'n.csv')
  self.assertEqual(code,0,err);self.assertIn('fields',generate.call_args.args[1]);self.assertIn('field_delimiter',generate.call_args.args[1])
 def test_cli_copy_and_reverse_persist_staging(self):
  code,_,err=self.call('bom-format','customize',self.path,'--template','Mine');self.assertEqual(code,0,err)
  p=self.dir/'plan.json';code,_,err=self.call('bom-format','preview',self.path,'--template','Mine','--output',p);self.assertEqual(code,0,err)
  original=self.path.read_bytes();code,_,err=self.call('bom-format','apply',self.path,'--plan',p,'--confirm','FORMAT','--acknowledge-replacement');self.assertEqual(code,0,err);self.assertEqual(original,self.path.read_bytes());self.assertIsNotNone(Workspace(Project(self.path)).state['native_bom_settings'])
 def test_reverse_scoped_expression_refused(self):
  nf.customize(self.ws,'Mine');self.ws.state['templates']['Mine']['columns'][1]['field']='${PROJECT:REV}'
  with self.assertRaisesRegex(ValueError,'scoped'):nf.reverse_preview(self.ws,'Mine')
 def test_reverse_scoped_label_refused(self):
  nf.customize(self.ws,'Mine');self.ws.state['templates']['Mine']['columns'][1]['label']='${PROJECT:REV}'
  with self.assertRaisesRegex(ValueError,'scoped'):nf.reverse_preview(self.ws,'Mine')
 def test_unresolved_native_column_not_silent_blank(self):
  self.ws.project.pro.setdefault('schematic',{})['bom_settings']={'name':'Expr','fields_ordered':[{'name':'${NO_SUCH_VAR}','label':'Unknown','show':True,'group_by':False}]}
  d=self.ws.public();self.assertEqual(d['rows'][0]['fields']['${NO_SUCH_VAR}'],'${NO_SUCH_VAR}');self.assertTrue(d['rows'][0]['native_view_warnings'])
 def test_native_preview_request_carries_saved_settings(self):
  with patch('bomstudio.nativebom.generate',return_value={'data':b'Native test','command':[],'notice':'contract'}) as generate:
   code,raw=self.request('bom-format/preview',{'acknowledge_saved':True})
  self.assertEqual(code,200);self.assertEqual(json.loads(raw)['text'],'Native test');self.assertIn('group_by',generate.call_args.args[1])

if __name__=='__main__':unittest.main()
