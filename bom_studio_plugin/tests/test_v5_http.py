"""Authenticated quantitative reports; no external network or KiCad host."""
import io,json,unittest,zipfile
import test_http as base_http
from bomstudio.engine import Workspace
from bomstudio.native import Project,BASE

class V5HTTPTests(unittest.TestCase):
 setUpClass=classmethod(base_http.HTTPTests.setUpClass.__func__)
 tearDownClass=classmethod(base_http.HTTPTests.tearDownClass.__func__)
 request=base_http.HTTPTests.request
 def setUp(self):
  self.app.workspace=Workspace(Project(self.app.workspace.project.pro_path));ws=self.app.workspace
  ws.edit([r['id'] for r in ws.rows()],BASE,{'Rate':'2','Mass':'100mg','Dissipation':'250mW','Temp_Max':'75 C'})
 def post(self,route,body):return self.request('/api/'+route,'POST',body)
 def test_analytics_auth(self):self.assertEqual(self.request('/api/analytics/run','POST',{},auth=False)[0],401)
 def test_validate_no_mutation(self):
  before=self.app.workspace._serialize();code,raw,_=self.post('analytics/validate',{'config':{'price_field':'Rate'}});self.assertEqual(code,200);self.assertEqual(json.loads(raw)['config']['price_field'],'Rate');self.assertEqual(before,self.app.workspace._serialize())
 def test_invalid_validation(self):self.assertEqual(self.post('analytics/validate',{'config':{'price_per':0}})[0],400)
 def test_setting_persistence_staged(self):
  code,raw,_=self.post('analytics/settings',{'settings':{'price_field':'Rate'}});self.assertEqual(code,200);self.assertFalse(json.loads(raw)['native_files_written']);self.assertEqual(self.app.workspace.state['analytics_settings']['price_field'],'Rate');self.app.workspace.project.check_unchanged()
 def test_readonly_report_custom_mapping(self):
  before=self.app.workspace._serialize();code,raw,_=self.post('analytics/run',{'config':{'price_field':'Rate','query':'Reference=R1'}});self.assertEqual(code,200);self.assertEqual(json.loads(raw)['mass']['known_per_board'],'0.1');self.assertEqual(before,self.app.workspace._serialize())
 def test_excel_attachment(self):
  code,raw,headers=self.post('analytics/export',{'format':'xlsx','config':{'price_field':'Rate'}});self.assertEqual(code,200);self.assertIn('attachment',headers['Content-Disposition']);self.assertIsNone(zipfile.ZipFile(io.BytesIO(raw)).testzip())
 def test_csv_table(self):
  code,raw,_=self.post('analytics/export',{'format':'csv','table':'groups'});self.assertEqual(code,200);self.assertIn(b'Known mass g',raw)
 def test_invalid_format(self):self.assertEqual(self.post('analytics/export',{'format':'exe'})[0],400)
 def test_threshold(self):
  code,raw,_=self.post('threshold',{'field':'Temp_Max','condition':'<80'});self.assertEqual(code,200);self.assertEqual(json.loads(raw)['matched'],11)
 def test_threshold_missing_bad_request(self):self.assertEqual(self.post('threshold',{'field':'Unknown','condition':'<80'})[0],400)
 def test_unit_aware_query_shared(self):
  code,raw,_=self.post('query',{'query':'Temp_Max<80'});self.assertEqual(code,200);self.assertEqual(json.loads(raw)['matched'],11)
 def test_analytics_asset(self):
  code,raw,h=self.request('/analytics.js');self.assertEqual(code,200);self.assertIn(b'renderAnalytics',raw);self.assertIn('script-src',h['Content-Security-Policy'])
