"""Late numerical jobs cannot restore results for edited analysis inputs."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


FLOW=r'''
import sys,time,threading,traceback
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import wx
from quick_pi_plugin.ui import QuickPIFrame
from quick_therm_plugin.ui import QuickThermFrame
app=wx.App(False)
path=Path(sys.argv[1])/'quick_therm_plugin/examples/thermal-demo.kicad_pcb'
cases={'pi':(QuickPIFrame,'_invalidate'),'therm':(QuickThermFrame,'_invalidate_thermal')}
cls,invalidator=cases[sys.argv[2]]
with patch.object(cls,'_inspect'):frame=cls(None,path)
frame.Show();release=threading.Event();received=[];errors=[];done=[]
deadline=time.monotonic()+8

def fail():
 errors.append(traceback.format_exc());frame.Close()

def check(phase):
 try:
  assert time.monotonic()<deadline,'Native callback timed out'
  if frame._busy:wx.CallLater(10,check,phase);return
  if phase==1:
   assert received==[],received
   frame._task(lambda:42,received.append,'Fresh controlled test')
   wx.CallLater(10,check,2)
  else:
   assert received==[42],received
   done.append(True);frame.Close()
 except Exception:fail()

def start():
 try:
  frame._task(lambda:release.wait(4) or 42,received.append,'Pending controlled test')
  getattr(frame,invalidator)();assert frame._cancel.is_set()
  release.set();wx.CallLater(10,check,1)
 except Exception:fail()
wx.CallLater(80,start);app.MainLoop()
assert not errors,errors
assert done,'Native workflow did not finish'
print('PI/Therm edited inputs reject late results; fresh jobs still complete.')
'''


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                     'Native KiCad wxPython required')
class AnalysisLifecycleTests(unittest.TestCase):
    def test_changed_inputs_discard_late_job_result(self):
        root=Path(__file__).resolve().parents[1]
        for kind in ('pi','therm'):
            with self.subTest(kind=kind):
                result=subprocess.run([sys.executable,'-c',FLOW,str(root),kind],capture_output=True,text=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
