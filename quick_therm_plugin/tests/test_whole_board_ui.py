"""Actual native whole-board action/worker lifecycle in a fresh interpreter."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from quick_therm_plugin.quick_therm import restored_field_mapping


class FieldMappingTests(unittest.TestCase):
    def test_unique_alias_and_explicit_choice_preserved(self):
        names=['Power_W','RthetaJA','RthetaJB','RthetaJC','ReviewedWatts']
        mapping=restored_field_mapping(names,{'power_w':'ReviewedWatts'})
        self.assertEqual(mapping,{'power_w':'ReviewedWatts','theta_ja_air_k_per_w':'RthetaJA',
                                  'theta_jb_k_per_w':'RthetaJB','theta_jc_k_per_w':'RthetaJC'})

    def test_ambiguous_or_missing_fields_never_invent_a_mapping(self):
        mapping=restored_field_mapping(['Power','Power_W','RthetaJA','RJA'])
        self.assertTrue(all(value=='' for value in mapping.values()))


NATIVE_FLOW=r'''
from pathlib import Path
import sys
import time
import faulthandler
from unittest.mock import patch

root=Path(sys.argv[1]);target=Path(sys.argv[2]);sys.path.insert(0,str(root))
faulthandler.dump_traceback_later(20)
from quick_therm_plugin.ui import QuickThermFrame
import pcbnew
board=pcbnew.LoadBoard(str(root/'mechanical_check_plugin/tests/fixtures/validation-fixture.kicad_pcb'))
footprints=list(board.GetFootprints())
part=next(footprint for footprint in footprints if footprint.GetReference()=='C1')
part.SetField('Power_W','0.5 W');part.SetField('RthetaJA','40 K/W')
part.SetField('RthetaJB','5 K/W');part.SetField('Tmax','85')
for footprint in footprints:
    if footprint.GetReference()!='C1':board.Remove(footprint)
pcbnew.SaveBoard(str(target),board)
del part,footprint,footprints,board
print('Native fixture saved before App',flush=True)
original=target.read_bytes()
import wx
state={'phase':'inspect','failure':None};started=time.monotonic()
with patch('wayricad_runtime.runtime_setup.ensure_runtime',return_value=Path(sys.executable)):
    app=wx.App(False);app.SetExitOnFrameDelete(False)
    print('Native App created',flush=True)
    frame=QuickThermFrame(None,target);app.SetTopWindow(frame);frame.Show()
    print('Native frame shown',flush=True)
    def close():
        frame.Close();app.ExitMainLoop()
    def check():
        try:
            assert time.monotonic()-started<60,'Native workflow exceeded its bounded deadline.'
            if state['phase']=='inspect' and frame.inventory and not frame._busy:
                print('Native inspection complete',flush=True)
                assert frame.inventory['component_references']==['C1']
                assert frame.therm_refs.IsChecked(0),'checked component scope'
                assert frame.therm_power.GetValue()=='Power_W','power mapping'
                assert frame.therm_ja.GetValue()=='RthetaJA'
                frame.manual_values={'C1':{'power_w':.5,'theta_ja_air_k_per_w':40,'theta_jb_k_per_w':5}}
                frame.therm_limit_max.SetValue('Tmax')
                state['phase']='reload';frame._inspect()
            elif state['phase']=='reload' and frame.inventory and not frame._busy:
                print('Native reload complete',flush=True)
                assert frame.manual_values['C1']['theta_ja_air_k_per_w']==40,'reload RJA'
                assert frame.manual_values['C1']['theta_jb_k_per_w']==5,'reload RJB'
                assert frame.therm_refs.IsChecked(0),'checked component scope'
                assert frame.therm_power.GetValue()=='Power_W','power mapping'
                assert frame.therm_limit_max.GetValue()=='Tmax','limit mapping'
                frame.therm_model_kind.SetSelection(1)
                frame.therm_dielectric_k.ChangeValue('.42');frame.therm_plating.ChangeValue('.025')
                frame.thermal_bundle={'quick_therm':{'model':'previous'}};frame._buttons()
                assert frame.therm_export.IsEnabled(),'previous export state'
                event=wx.CommandEvent(wx.EVT_BUTTON.typeId,frame.therm_whole_board.GetId())
                frame.therm_whole_board.GetEventHandler().ProcessEvent(event)
                assert frame.therm_model_enabled.GetValue() and not frame.therm_model.IsCollapsed(),'model setup visible'
                assert frame.therm_model_kind.GetSelection()==1,'retained model choice'
                assert frame.therm_dielectric_k.GetValue()=='.42' and frame.therm_plating.GetValue()=='.025','retained material inputs'
                assert frame.manual_values['C1']['power_w']==.5 and frame.therm_refs.IsChecked(0),'retained power and scope'
                assert not frame.therm_export.IsEnabled() and not frame.thermal_bundle,'stale export invalidated'
                assert hasattr(frame,'therm_time_enabled') and hasattr(frame,'therm_probe_button')
                frame.therm_model_kind.SetSelection(0);frame._therm_controls()
                frame.therm_input_mode.SetSelection(0);frame._input_mode_changed(None)
                frame.therm_ambient.ChangeValue('25');frame.therm_k.ChangeValue('35')
                frame.therm_emissivity.ChangeValue('.8');frame.therm_air_board.ChangeValue('1')
                frame.therm_grid.SetValue(12)
                state['phase']='run';frame.on_quick_therm()
                print('Native requested study: '+frame.therm_status.GetLabel(),flush=True)
            elif state['phase']=='run' and frame.thermal_bundle and not frame._busy:
                print('Native physical study complete',flush=True)
                bundle=frame.thermal_bundle;network=bundle['thermal_network'];field=network['board_field']
                assert network['status']=='converged'
                assert field['value_location']=='finite_volume_cell'
                assert field['values_c'][0][0]>25 and field['values_c'][-1][-1]>25
                assert abs(network['heat_balance']['residual_w'])<1e-5
                assert frame.therm_mode.GetStringSelection()=='Top board model'
                assert frame.therm_figure.axes and frame.therm_table.GetItemCount()==1
                assert target.read_bytes()==original
                frame.therm_mode.SetStringSelection('Bottom-side map')
                frame._thermal_mode_changed();frame._accept_therm(bundle)
                assert frame.therm_mode.GetStringSelection()=='Bottom-side map'
                frame._add_thermal_probe(30,20,'Top board model')
                assert len(frame.therm_probe_definitions)==1 and frame.therm_probe_table.GetItemCount()==1
                frame._inspect();state['phase']='final_reload'
            elif state['phase']=='final_reload' and frame.inventory and not frame._busy:
                assert frame.manual_values['C1']['power_w']==.5 and frame.therm_refs.IsChecked(0),'retained power and scope'
                assert not frame.thermal_bundle and not frame.therm_export.IsEnabled()
                assert target.read_bytes()==original
                state['phase']='complete';wx.CallLater(100,close);return
            wx.CallLater(100,check)
        except BaseException as error:
            state['failure']=repr(error);print('Native workflow failure: '+repr(error),flush=True)
            wx.CallAfter(close)
    wx.CallLater(100,check);app.MainLoop()
if state['failure'] or state['phase']!='complete':raise RuntimeError(state)
faulthandler.cancel_dump_traceback_later()
print('Native real button / async worker / whole outline / reload / explicit view / probes / ordinary close passed',flush=True)
'''

MANUAL_FLOW=r'''
import sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from quick_therm_plugin.manual_setup import ManualThermalDialog
import wx
app=wx.App(False);app.SetExitOnFrameDelete(False)
frame=wx.Frame(None);frame.Show()
existing={'C1':{'power_w':.5,'theta_ja_air_k_per_w':40,'theta_jb_k_per_w':5,'theta_jc_k_per_w':2}}
with ManualThermalDialog(frame,['C1'],'air',set(),existing) as dialog:
    dialog.Show();wx.Yield()
    dialog.grid.SetGridCursor(0,0);dialog.grid.EnableCellEditControl()
    editor=dialog.grid.GetCellEditor(0,0);editor.GetControl().SetValue('.75 W')
    with patch.object(dialog,'EndModal') as end:dialog._accept(None)
    editor.DecRef();end.assert_called_once_with(wx.ID_OK)
    assert dialog.values['C1']=={**existing['C1'],'power_w':.75},dialog.values
    dialog.Hide()
with ManualThermalDialog(frame,['C1'],'air',set(),existing,power_only=True) as dialog:
    dialog.Show();wx.Yield();dialog.grid.SetCellValue(0,1,'')
    with patch.object(dialog,'EndModal') as end:dialog._accept(None)
    end.assert_called_once_with(wx.ID_OK)
    assert 'theta_jb_k_per_w' not in dialog.values['C1']
    assert dialog.values['C1']['theta_ja_air_k_per_w']==40 and dialog.values['C1']['theta_jc_k_per_w']==2
    dialog.Hide()
frame.Destroy();wx.Yield();app.Destroy()
print('Native active grid edit, retained independent paths, explicit optional path clearing passed',flush=True)
'''


class NativeWholeBoardWorkflowTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                         'Native KiCad wx/pcbnew bindings unavailable')
    def test_manual_active_edit_and_independent_paths_in_separate_process(self):
        root=Path(__file__).resolve().parents[2]
        run=subprocess.run([sys.executable,'-B','-I','-c',MANUAL_FLOW,str(root)],
                           capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+'\n'+run.stderr)
        self.assertIn('explicit optional path clearing passed',run.stdout)

    @unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),
                         'Native KiCad wx/pcbnew bindings unavailable')
    def test_actual_button_async_worker_and_normal_window_close(self):
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'native-window.log'
            # File capture keeps any worker child from retaining an inherited
            # pipe reader and exposes the window's actual return code directly.
            with log.open('w',encoding='utf-8') as output:
                try:
                    run=subprocess.run([sys.executable,'-B','-I','-c',NATIVE_FLOW,str(root),
                                        str(Path(directory)/'whole-board.kicad_pcb')],
                                       stdout=output,stderr=subprocess.STDOUT,text=True,timeout=90)
                except subprocess.TimeoutExpired:
                    output.flush()
                    self.fail('Bounded native process timed out:\n'+log.read_text(encoding='utf-8'))
            diagnostic=log.read_text(encoding='utf-8')
        self.assertEqual(run.returncode,0,diagnostic)
        self.assertIn('ordinary close passed',diagnostic)


if __name__=='__main__':unittest.main()
