import http.client
import json
from pathlib import Path
import shutil
import threading
import unittest
from bomstudio.server import Application,Server

class HTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.app=Application(demo=True);cls.server=Server(cls.app)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.server.server_close();cls.thread.join();shutil.rmtree(cls.app.demo_directory)
 def request(self,path='/api/state',method='GET',body=None,headers=None,auth=True):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
  h={'X-Bom-Token':self.app.token} if auth else {}
  if body is not None:h['Content-Type']='application/json';body=json.dumps(body)
  h.update(headers or {});c.request(method,path,body=body,headers=h);r=c.getresponse();data=r.read();status=r.status;rh=dict(r.getheaders());c.close();return status,data,rh
 def test_state_authenticated(self):
  status,data,_=self.request();self.assertEqual(status,200);self.assertEqual(json.loads(data)['stats']['parts'],11)
 def test_missing_auth_denied(self):self.assertEqual(self.request(auth=False)[0],401)
 def test_wrong_auth_denied(self):self.assertEqual(self.request(headers={'X-Bom-Token':'wrong'})[0],401)
 def test_dns_rebinding_host_denied(self):self.assertEqual(self.request(headers={'Host':'evil.test'})[0],403)
 def test_cross_origin_denied(self):self.assertEqual(self.request(headers={'Origin':'https://evil.test'})[0],403)
 def test_matching_origin_allowed(self):self.assertEqual(self.request(headers={'Origin':self.server.origin})[0],200)
 def test_index_loads(self):self.assertEqual(self.request('/',auth=False)[0],200)
 def test_static_path_traversal_blocked(self):self.assertEqual(self.request('/../bomstudio/server.py',auth=False)[0],404)
 def test_csp_and_no_store(self):
  _,_,headers=self.request('/');self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy']);self.assertEqual(headers['Cache-Control'],'no-store')
 def test_bad_content_type_rejected(self):self.assertEqual(self.request('/api/settings','POST',{},headers={'Content-Type':'text/plain'})[0],400)
 def test_export_attachment(self):
  status,data,headers=self.request('/api/export','POST',{'template':'Purchasing','format':'xlsx'});self.assertEqual(status,200);self.assertTrue(data.startswith(b'PK'));self.assertIn('attachment',headers['Content-Disposition'])
 def test_missing_project_path_reports_error(self):self.assertEqual(self.request('/api/open','POST',{'path':'/a/path/that/does/not/exist.kicad_pro'})[0],400)
 def test_unknown_route_no_write(self):self.assertEqual(self.request('/api/run-shell','POST',{'command':'no'})[0],400)
 def test_variant_matrix(self):
  status,data,_=self.request('/api/matrix','POST',{});m=json.loads(data)
  self.assertEqual(status,200);self.assertEqual(len(m['variants']),3);self.assertEqual(len(m['rows']['Economy']),11)
 def test_no_remote_bind(self):self.assertEqual(self.server.server_address[0],'127.0.0.1')

if __name__=='__main__':unittest.main()
