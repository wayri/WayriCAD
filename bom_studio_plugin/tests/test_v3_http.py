"""Authenticated endpoints, using a synthetic local project only."""
import json,unittest
import test_http as base_http
from bomstudio.engine import Workspace
from bomstudio.native import Project

class V3HTTPTests(unittest.TestCase):
 setUpClass=classmethod(base_http.HTTPTests.setUpClass.__func__)
 tearDownClass=classmethod(base_http.HTTPTests.tearDownClass.__func__)
 request=base_http.HTTPTests.request
 def setUp(self):self.app.workspace=Workspace(Project(self.app.workspace.project.pro_path))
 def post(self,route,body):return self.request('/api/'+route,'POST',body)
 def test_health_authenticated(self):
  code,data,_=self.post('health/run',{});self.assertEqual(code,200);r=json.loads(data);self.assertEqual(r['schema'],'wayricad-health-1');self.assertGreater(r['summary']['unknowns'],0)
 def test_health_auth_required(self):self.assertEqual(self.request('/api/health/run','POST',{},auth=False)[0],401)
 def test_analyzer_no_write(self):
  before=self.app.workspace._serialize();code,data,_=self.post('analyzer/run',{});self.assertEqual(code,200);self.assertEqual(before,self.app.workspace._serialize())
 def test_report_json_attachment(self):
  code,data,h=self.post('health/export',{'kind':'health'});self.assertEqual(code,200);self.assertIn('attachment',h['Content-Disposition']);self.assertEqual(json.loads(data)['schema'],'wayricad-health-1')
 def test_report_kind_rejected(self):self.assertEqual(self.post('health/export',{'kind':'../../bad'})[0],400)
 def test_grouping_custom_fields(self):
  code,data,_=self.post('grouping/settings',{'fields':['Value','Footprint']});self.assertEqual(code,200);self.assertEqual(self.app.workspace.state['grouping']['fields'],['Value','Footprint'])
 def test_grid_review_then_apply(self):
  ws=self.app.workspace;r=next(r for r in ws.rows() if r['ref']=='R1');entries=[{'ids':[r['id']],'changes':{'Value':'10000Ohm'}}]
  code,data,_=self.post('grid/preview',{'entries':entries});self.assertEqual(code,200);plan=json.loads(data);self.assertEqual(next(r for r in ws.rows() if r['ref']=='R1')['fields']['Value'],'10k')
  code,_,_=self.post('grid/apply',{'entries':entries,'fingerprint':plan['fingerprint'],'confirmation':'EDIT'});self.assertEqual(code,200);ws.project.check_unchanged()
 def test_grid_computed_field_rejected(self):
  r=self.app.workspace.rows()[0];self.assertEqual(self.post('grid/preview',{'entries':[{'ids':[r['id']],'changes':{'Reference':'R999'}}]})[0],400)
 def test_supplier_csv_no_keys(self):
  code,data,h=self.post('supplier/request',{'supplier':'Mouser'});self.assertEqual(code,200);self.assertIn(b'Manufacturer Part Number',data)
 def test_evidence_review_gate(self):
  payload={'format':'manual','record':{'mpn':'TEST','manufacturer':'Fixture'}};code,data,_=self.post('evidence/preview',{'payload':payload});self.assertEqual(code,200)
  b={'payload':payload,'fingerprint':json.loads(data)['fingerprint'],'confirmation':'IMPORT','reviewed':False};self.assertEqual(self.post('evidence/apply',b)[0],400);self.assertEqual(self.app.workspace.state['evidence'],[])
 def test_health_settings_validate(self):self.assertEqual(self.post('health/settings',{'settings':{'stock_age_hours':-1}})[0],400)
 def test_table_headers(self):
  code,data,_=self.post('evidence/inspect',{'payload':{'format':'csv','text':'MPN,Manufacturer,Quantity Available\nTEST,Fixture,10'}});self.assertEqual(code,200);self.assertEqual(json.loads(data)['mapping']['stock'],'Quantity Available')
if __name__=='__main__':unittest.main()
