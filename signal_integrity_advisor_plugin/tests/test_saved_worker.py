"""Worker isolation, source provenance and cancellation contracts."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from signal_integrity_advisor_plugin import service

class SavedWorkerTests(unittest.TestCase):
 def test_fingerprints_include_absent_rule_files_and_reject_changes(self):
  with tempfile.TemporaryDirectory() as directory:
   board=Path(directory)/'board.kicad_pcb';board.write_text('board',encoding='utf-8')
   fingerprints=service.source_fingerprints(board)
   self.assertEqual(len(fingerprints),3)
   request={'board_path':str(board),'source_fingerprints':fingerprints};self.assertEqual(service.require_source(request),fingerprints)
   board.with_suffix('.kicad_pro').write_text('rules',encoding='utf-8')
   with self.assertRaisesRegex(ValueError,'project rules changed'):service.require_source(request)
 def test_cancellation_before_runtime_setup_does_not_launch(self):
  with patch('subprocess.Popen') as popen:
   with self.assertRaises(InterruptedError):service.run_job({},cancelled=lambda:True)
   popen.assert_not_called()
 def test_timeout_is_bounded(self):
  for value in (0,-1,float('nan'),float('inf')):
   with self.assertRaises(ValueError):service.run_job({},timeout=value)
 def test_native_objects_are_reattached_by_exact_unique_uuid(self):
  row=lambda uid:NS(m_Uuid=NS(AsString=lambda:uid))
  item=row('track');board=NS(GetTracks=lambda:[item],Zones=lambda:[])
  payload={'path_data':{'net_name':'N','start_pad':'A.1','end_pad':'B.1','status':'partial'},'board_item_ids':['track']}
  restored=service.restore_path(payload,board);self.assertIs(restored.board_items[0],item)
  payload['board_item_ids']=['missing']
  with self.assertRaisesRegex(ValueError,'no longer matches'):service.restore_path(payload,board)
  payload['board_item_ids']=['track','track']
  with self.assertRaises(ValueError):service.restore_path(payload,board)
 def test_owned_process_is_terminated_on_cancel(self):
  class Process:
   returncode=None
   def __init__(self):self.terminated=0;self.polls=0
   def poll(self):return None if self.returncode is None else self.returncode
   def terminate(self):self.terminated+=1;self.returncode=-1
   def wait(self,timeout):return self.returncode
  process=Process();calls=iter([False,False,True])
  with patch('subprocess.Popen',return_value=process),patch('wayricad_runtime.runtime_setup.child_environment',return_value={}):
   with self.assertRaises(InterruptedError):service.run_job({},cancelled=lambda:next(calls),python='python')
  self.assertEqual(process.terminated,1)

try:
 import wx
except ImportError:
 wx=None

@unittest.skipIf(wx is None,'Native wx runtime is required')
class SavedUIEventTests(unittest.TestCase):
 def test_changed_input_generation_cannot_apply_finished_result(self):
  from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
  messages=[];enabled=[]
  panel=NS(_closed=False,_job_serial=2,_generation=7,_busy=True,
           run_button=NS(Enable=lambda:enabled.append('run')),cancel_button=NS(Disable=lambda:enabled.append('cancel')),
           status=NS(SetLabel=messages.append))
  QuickSIPanel._finished(panel,2,6,{}, {},{'report':{'stale':True}},None)
  self.assertFalse(panel._busy);self.assertIn('inputs changed',messages[-1]);self.assertEqual(enabled,['run','cancel'])
 def test_destroyed_panel_ignores_completed_result(self):
  from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
  panel=NS(_closed=True)
  QuickSIPanel._finished(panel,1,1,{}, {},None,None)

if __name__=='__main__':unittest.main()
