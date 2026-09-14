"""v0.4 authenticated query/recipe/link/job-set endpoints."""
import io,json,unittest,zipfile
from pathlib import Path
import test_http as base_http
from bomstudio.engine import Workspace
from bomstudio.native import Project
from bomstudio.bridge import SelectionService
from test_v4 import FakeBoard,FakeClient

class V4HTTPTests(unittest.TestCase):
 setUpClass=classmethod(base_http.HTTPTests.setUpClass.__func__)
 tearDownClass=classmethod(base_http.HTTPTests.tearDownClass.__func__)
 request=base_http.HTTPTests.request
 def setUp(self):self.app.workspace=Workspace(Project(self.app.workspace.project.pro_path));self.app.link.call('close')
 def post(self,route,body):return self.request('/api/'+route,'POST',body)
 def test_advanced_query(self):
  code,data,_=self.post('query',{'query':'Reference~"R*" AND Value=10k'});self.assertEqual(code,200);self.assertEqual(json.loads(data)['matched'],3)
 def test_query_invalid_no_mutation(self):
  before=self.app.workspace._serialize();code,_,_=self.post('query',{'query':'Value='});self.assertEqual(code,400);self.assertEqual(before,self.app.workspace._serialize())
 def test_query_auth_required(self):self.assertEqual(self.request('/api/query','POST',{'query':'R1'},auth=False)[0],401)
 def test_save_share_import_filter(self):
  self.assertEqual(self.post('filter/save',{'name':'10k','record':{'query':'Value=10k'}})[0],200);code,data,h=self.post('filter/export',{});self.assertEqual(code,200);self.assertIn('attachment',h['Content-Disposition']);payload=json.loads(data);self.assertEqual(payload['schema'],'wayricad-filters-1');self.assertEqual(self.post('filter/import',{'payload':payload})[0],400);self.assertEqual(self.post('filter/import',{'payload':payload,'replace':True})[0],200)
 def test_bulk_review_and_apply(self):
  r={'query':'Reference=R1','operations':[{'op':'set','field':'Value','value':'22k'}]};code,data,_=self.post('bulk/preview',{'recipe':r});self.assertEqual(code,200);plan=json.loads(data);self.assertEqual(plan['matched'],1);body={'recipe':r,'fingerprint':plan['fingerprint'],'confirmation':'YES'};self.assertEqual(self.post('bulk/apply',body)[0],400);body['confirmation']='EDIT';self.assertEqual(self.post('bulk/apply',body)[0],200);self.app.workspace.project.check_unchanged()
 def test_bulk_unknown_keys(self):self.assertEqual(self.post('bulk/preview',{'recipe':{'query':'R1','exec':'bad','operations':[]}})[0],400)
 def test_jobset_attachment_structure(self):
  dest=str(self.app.workspace.project.root.parent/'jobs');code,data,h=self.post('jobset/bundle',{'directory':dest});self.assertEqual(code,200);self.assertIn('attachment',h['Content-Disposition']);z=zipfile.ZipFile(io.BytesIO(data));self.assertIsNone(z.testzip());self.assertIn('WayriCAD_BOM.kicad_jobset',z.namelist());self.assertFalse(Path(dest).exists())
 def test_jobset_empty_directory_rejected(self):self.assertEqual(self.post('jobset/bundle',{'directory':''})[0],400)
 def test_link_disconnected_poll_and_diagnostic(self):
  code,data,_=self.post('link/poll',{});self.assertEqual(code,200);self.assertFalse(json.loads(data)['connected']);code,data,_=self.post('link/diagnostic',{});self.assertEqual(code,200);self.assertFalse(json.loads(data)['host_tested'])
 def test_link_does_not_accept_remote_transport(self):self.assertEqual(self.post('link/connect',{'options':{'socket':'https://host'}})[0],400)
 def test_link_unknown_action_refused(self):self.assertEqual(self.post('link/run_action',{'action':'deleteAll'})[0],400)
 def test_link_selection_injected_driver(self):
  previous=self.app.link;board=FakeBoard(self.app.workspace.project);client=FakeClient(board);self.app.link=SelectionService(lambda **kwargs:client)
  try:
   code,data,_=self.post('link/connect',{'options':{}});self.assertEqual(code,200);self.assertTrue(json.loads(data)['connected']);r=self.app.workspace.rows()[0];code,data,_=self.post('link/select',{'ids':[r['id']]});self.assertEqual(code,200);self.assertEqual(json.loads(data)['ids'],[r['id']]);self.app.workspace.project.check_unchanged()
  finally:self.app.link.close();self.app.link=previous
 def test_automation_asset_served(self):
  code,data,h=self.request('/automation.js');self.assertEqual(code,200);self.assertIn(b'reviewBulk4',data);self.assertIn('script-src',h['Content-Security-Policy'])

if __name__=='__main__':unittest.main()
