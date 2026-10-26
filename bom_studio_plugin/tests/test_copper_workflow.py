"""Actual board-only copper jobs and export/source boundaries."""
import hashlib,http.client,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from bomstudio.server import Application,Server
from bomstudio import copper_jobs,copper_exports
BOARD='(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 1 "GND") (gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts")) (segment (start 1 1) (end 9 1) (width 1) (layer "F.Cu") (net 1)))'
class CopperWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.board=self.root/'board-only.kicad_pcb';self.board.write_text(BOARD,encoding='utf-8');self.before=self.board.read_bytes()
  self.app=Application(self.board,auto_link=False);self.server=Server(self.app);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join(5);self.temp.cleanup()
 def post(self,path,body):
  conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
  try:
   conn.request('POST','/api/'+path,json.dumps(body),{'X-Bom-Token':self.app.token,'Content-Type':'application/json'});response=conn.getresponse();return response.status,response.read()
  finally:conn.close()
 def wait(self,identifier):
  until=time.monotonic()+15
  while time.monotonic()<until:
   code,raw=self.post('copper/status',{'id':identifier,'include_result':True});self.assertEqual(code,200);task=json.loads(raw)
   if task['state']!='running':return task
   time.sleep(.05)
  self.fail('Copper fixture exceeded test budget')
 def test_board_only_job_exports_and_stale_source(self):
  self.assertIsNone(self.app.workspace);self.assertTrue(Path(self.app.state()['board_path']).samefile(self.board))
  code,raw=self.post('copper/start',{});self.assertEqual(code,200);identifier=json.loads(raw)['id'];task=self.wait(identifier);self.assertEqual(task['state'],'ready',task)
  report=task['result'];self.assertGreater(report['layers'][0]['copper_area_mm2'],0);self.assertEqual(report['source']['sha256'],hashlib.sha256(self.before).hexdigest())
  for format in ('json','csv','tsv','html'):
   code,data=self.post('copper/export',{'id':identifier,'format':format,'table':'net_layers'});self.assertEqual(code,200,(format,data));self.assertTrue(data)
  self.assertEqual(self.board.read_bytes(),self.before);self.board.write_text(BOARD+' ');self.assertEqual(self.post('copper/export',{'id':identifier})[0],400)
 def test_server_close_waits_for_owned_job_cleanup(self):
  started=threading.Event();cleaned=threading.Event()
  def slow(path,progress,cancel):
   started.set()
   while not cancel():time.sleep(.01)
   time.sleep(.1);cleaned.set();raise InterruptedError()
  with patch.object(copper_jobs,'run',side_effect=slow):
   code,raw=self.post('copper/start',{});self.assertEqual(code,200);self.assertTrue(started.wait(2))
   self.server.shutdown();self.server.server_close();self.assertTrue(cleaned.is_set())

 def test_cancellation_discards_partial_result(self):
  started=threading.Event()
  def slow(path,progress,cancel):
   started.set()
   while not cancel():time.sleep(.01)
   raise InterruptedError()
  with patch('bomstudio.copper_jobs.run',side_effect=slow):
   code,raw=self.post('copper/start',{});self.assertEqual(code,200);identifier=json.loads(raw)['id'];self.assertTrue(started.wait(2));self.assertEqual(self.post('copper/start',{})[0],400);self.post('copper/cancel',{'id':identifier});task=self.wait(identifier);self.assertEqual(task['state'],'canceled');self.assertIsNone(task['result'])
  self.assertEqual(self.board.read_bytes(),self.before)
 def test_missing_geometry_fails_before_job(self):
  self.app.copper_available=False;self.assertEqual(self.post('copper/start',{})[0],400);self.assertFalse(self.app.copper_tasks.items)
 def test_precancel_and_bad_budgets_do_not_launch(self):
  with patch('bomstudio.copper_jobs.subprocess.Popen') as launch:
   with self.assertRaises(InterruptedError):copper_jobs.run(self.board,cancelled=lambda:True)
   launch.assert_not_called()
  for timeout in (0,float('nan'),601):
   with self.assertRaises(ValueError):copper_jobs.run(self.board,timeout=timeout)
 def test_timeout_terminates_owned_worker(self):
  process=unittest.mock.Mock();process.poll.return_value=None
  with patch('bomstudio.copper_jobs.subprocess.Popen',return_value=process),patch('bomstudio.copper_jobs.time.monotonic',side_effect=[0,2]):
   with self.assertRaises(TimeoutError):copper_jobs.run(self.board,timeout=1)
  process.terminate.assert_called_once();process.wait.assert_called_once_with(timeout=3);self.assertEqual(self.board.read_bytes(),self.before)
 def test_export_escapes_text_and_retains_unknowns(self):
  report={'source':{'path':'board.kicad_pcb','sha256':'a'*64},'status':'partial','nets':[{'net':'=bad<script>','copper_area_mm2':None}],'warnings':['<script>'],'summary':{}}
  raw,_,_=copper_exports.render(report,'csv','nets');self.assertIn("'=bad<script>",raw.decode('utf-8-sig'));raw,_,_=copper_exports.render(report,'html');self.assertNotIn(b'<script>',raw);self.assertIn(b'&lt;script&gt;',raw)
 def test_component_run_can_skip_expensive_copper_without_breaking_exports(self):
  from bomstudio import analytics,analytics_exports
  app=Application(demo=True)
  try:
   with patch('bomstudio.board_analytics.board_analysis',side_effect=AssertionError('Copper must be explicit')):
    report=analytics.run(app.workspace,include_board=False)
   self.assertEqual(report['board_analysis']['status'],'not_requested')
   self.assertTrue(analytics_exports.render(report,'html')[0])
  finally:
   import shutil
   app.link.close();shutil.rmtree(app.demo_directory)
 def test_cli_needs_no_schematic(self):
  from bomstudio.cli import main
  dest=self.root/'copper.json';self.assertEqual(main(['copper',str(self.board),'--output',str(dest)]),0);self.assertGreater(json.loads(dest.read_text(encoding='utf-8'))['layers'][0]['copper_area_mm2'],0);self.assertEqual(self.board.read_bytes(),self.before)
