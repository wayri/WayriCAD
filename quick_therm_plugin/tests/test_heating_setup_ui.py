"""Native guide lifecycle; skipped where wxPython is not installed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = r'''
from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
import wx
from unittest.mock import patch
from quick_therm_plugin.heating_setup_ui import HeatingStudyDialog
from quick_therm_plugin.ui import QuickThermFrame
from quick_therm_plugin.tests.test_heating_setup import settings
app=wx.App(False)
dialog=HeatingStudyDialog(None,settings(),[('U1',2.),('U2',None)],'Vacuum: explicit radiation and fixture conduction.',True,{'U1':[[0,1],[4,0]]})
dialog.Show();app.Yield()
dialog.SetSize((560,480));app.Yield();dialog._wrap_labels()
assert dialog.scroll.GetVirtualSize().width<=dialog.scroll.GetClientSize().width+2,(dialog.scroll.GetVirtualSize(),dialog.scroll.GetClientSize())
assert dialog.fields['duration_s'].IsEnabled()
dialog.fields['duration_s'].ChangeValue('2 min');dialog.fields['timestep_s'].ChangeValue('1 s')
dialog._smooth();assert dialog.fields['frame_interval_s'].GetValue()=='1.2'
assert dialog._values()['duration_s']==120
assert '101 regular stored frames' in dialog.advice.GetLabel()
dialog.fields['frame_interval_s'].ChangeValue('1 ms');dialog._refresh()
assert not dialog.run.IsEnabled() and '1000 stored frames' in dialog.advice.GetLabel()
dialog.mode.SetSelection(0);dialog._refresh()
assert dialog.run.IsEnabled() and not dialog.fields['duration_s'].IsEnabled()
dialog.Destroy();app.Yield()
# Actual frame applies the detached guide choices through the existing controls,
# invalidates prior results, and uses the ordinary worker validation on Run.
with patch.object(QuickThermFrame,'_inspect'):
 frame=QuickThermFrame(None,Path(sys.argv[1])/'quick_therm_plugin/examples/thermal-demo.kicad_pcb')
 app.Yield();frame.Maximize(False)
 frame.therm_time_duration.ChangeValue('10');frame.thermal_bundle={'quick_therm':{'model':'old'}}
 class Applied:
  def __init__(self,*args,**kwargs):
   from quick_therm_plugin.heating_setup import heating_settings
   self.settings=heating_settings(settings());self.settings['duration_s']=2.;self.run_after_apply=True
  def ShowModal(self):return wx.ID_OK
  def Destroy(self):pass
 with patch('quick_therm_plugin.heating_setup_ui.HeatingStudyDialog',Applied),patch.object(frame,'on_quick_therm') as run:
  frame.on_heating_study();assert run.call_count==1
 assert frame.therm_time_enabled.GetValue() and frame.therm_model_kind.GetSelection()==1
 assert frame.therm_time_duration.GetValue()=='2'
 assert not frame.thermal_bundle and not frame.therm_export.IsEnabled()
 assert frame.therm_study_setup.IsEnabled()
 frame.therm_inputs.load({'components':[{'reference':'U1'}]}, {}, {'U1':{'power_w':2.}}, ['U1'], {})
 frame.therm_power_schedule.ChangeValue('{}')
 import wx.grid,json
 def edit_watts():
  modal=next(window for window in wx.GetTopLevelWindows() if isinstance(window,wx.Dialog) and 'power steps' in window.GetTitle())
  grid=next(child for child in modal.GetChildren() if isinstance(child,wx.grid.Grid))
  assert grid.GetColLabelValue(2)=='Initially W' and grid.GetCellValue(0,2)=='2.0'
  grid.SetCellValue(0,2,'0.5');grid.SetCellValue(0,3,'1');grid.SetCellValue(0,4,'0')
  modal.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId,wx.ID_OK))
 wx.CallLater(100,edit_watts);frame._edit_power_steps()
 assert json.loads(frame.therm_power_schedule.GetValue())=={'U1':[[0.,.25],[1.,0.]]}
 assert frame.therm_schedule_interpolation.GetSelection()==1
 advanced='{"U1":[[0,1],[1,0],[2,1]]}'
 frame.therm_power_schedule.ChangeValue(advanced);frame._edit_power_steps()
 assert frame.therm_power_schedule.GetValue()==advanced
 frame._busy=True;frame._therm_controls();assert not frame.therm_study_setup.IsEnabled()
 frame._busy=False;frame.Close();app.Yield()
print('Native heating guide lifecycle passed')
'''


@unittest.skipUnless(importlib.util.find_spec('wx'), 'Native wxPython required')
class NativeHeatingSetupTests(unittest.TestCase):
    def test_guide_validation_apply_run_and_stale_result_lifecycle(self):
        root=Path(__file__).resolve().parents[2]
        completed=subprocess.run([sys.executable,'-c',SCRIPT,str(root)],capture_output=True,
                                 text=True,encoding='utf-8',timeout=35)
        self.assertEqual(completed.returncode,0,completed.stdout+'\n'+completed.stderr)
        self.assertIn('Native heating guide lifecycle passed',completed.stdout)
