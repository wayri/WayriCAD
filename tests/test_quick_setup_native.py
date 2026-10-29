"""Real native setup handlers restore inputs without rerunning or editing a PCB."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

try:
    import wx
    _NATIVE_LOG=wx.LogStderr()
    _PREVIOUS_LOG=wx.Log.SetActiveTarget(_NATIVE_LOG)
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
    from quick_therm_plugin.ui import QuickThermFrame
except ImportError:
    wx=None

_APP=None


@unittest.skipIf(wx is None,'KiCad native scientific GUI runtime required')
class QuickSetupNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _APP
        _APP=wx.GetApp() or wx.App(False)
        cls.app=_APP;cls.app.SetExitOnFrameDelete(False)

    def dialog(self,path,accepted=True):
        dialog=Mock();dialog.__enter__=Mock(return_value=dialog);dialog.__exit__=Mock(return_value=False)
        dialog.ShowModal.return_value=wx.ID_OK if accepted else wx.ID_CANCEL
        dialog.GetPath.return_value=str(path)
        return dialog

    def exercise(self,frame,module,path):
        original=module.capture(frame);board_bytes=Path(frame.board_path).read_bytes()
        with patch('wx.FileDialog',return_value=self.dialog(path)) as choose,patch('wx.MessageBox') as warning:
            frame.project_setup.on_save()
            self.assertTrue(path.is_file(),warning.call_args)
            self.assertEqual(choose.call_args.kwargs['defaultDir'],str(path.parent))
        if hasattr(frame,'voltage'):frame.voltage.ChangeValue('8.5')
        else:frame.therm_ambient.ChangeValue('76')
        with patch('wx.FileDialog',return_value=self.dialog(path)),patch('wx.MessageBox') as warning:
            frame.project_setup.on_load()
            warning.assert_not_called()
        self.assertEqual(module.capture(frame),original)
        with patch('wx.FileDialog',return_value=self.dialog(path,False)):
            frame.project_setup.on_load();frame.project_setup.on_save()
        self.assertEqual(module.capture(frame),original)
        self.assertEqual(Path(frame.board_path).read_bytes(),board_bytes)

    def test_pi_actual_handler_roundtrip_net_endpoints_and_returns(self):
        from quick_pi_plugin import setup_file
        with tempfile.TemporaryDirectory() as folder:
            board=Path(folder)/'example.kicad_pcb';pcbnew.SaveBoard(str(board),pcbnew.BOARD())
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,board);self.app.Yield()
                try:
                    rows=[dict(id=key,label=label,net=net,footprint_uuid=owner)
                          for key,label,net,owner in [('a','J1.1','VCC','j1'),('b','U1.1','VCC','u1'),('c','J1.2','GND','j1'),('d','U1.2','GND','u1')]]
                    frame.inventory={'nets':['VCC','GND'],'terminals':rows}
                    frame.net.Set(['VCC','GND']);frame.net.SetValue('VCC')
                    frame.return_signal.Set(['VCC','GND']);frame.return_signal.SetStringSelection('VCC')
                    frame.return_nets.Set(['VCC','GND']);frame.return_nets.Check(1,True)
                    frame._set_terminals();frame._return_nets_changed()
                    frame.return_source.SetSelection(1);frame.return_sink.SetSelection(2)
                    frame.voltage.ChangeValue('3.3');frame.current.ChangeValue('2.7')
                    self.exercise(frame,setup_file,Path(folder)/'inputs.json')
                    invalid=setup_file.capture(frame);invalid['endpoints']['source']='missing'
                    with self.assertRaises(ValueError):setup_file.validate(frame,invalid)
                finally:frame.Close();self.app.Yield()

    def test_thermal_actual_handler_roundtrip_manual_limits_and_transient(self):
        from quick_therm_plugin import setup_file
        with tempfile.TemporaryDirectory() as folder:
            board=Path(folder)/'example.kicad_pcb';pcbnew.SaveBoard(str(board),pcbnew.BOARD())
            with patch.object(QuickThermFrame,'_inspect'):
                frame=QuickThermFrame(None,board);self.app.Yield()
                try:
                    frame.inventory={'component_references':['U1'],'components':[{'reference':'U1'}],'field_names':[],'source_sha256':'f'*64}
                    for name in ('therm_power','therm_ja','therm_jb','therm_jc','therm_model_jb','therm_limit_min','therm_limit_max'):
                        getattr(frame,name).Set(['']);getattr(frame,name).SetValue('')
                    frame.therm_refs.Set(['U1']);frame.therm_refs.Check(0,True)
                    frame.manual_values={'U1':{'power_w':2,'theta_ja_air_k_per_w':30}}
                    frame.manual_temperature_limits={'U1':{'maximum_c':95}}
                    frame.therm_inputs.load(frame.inventory,{},dict(U1={**frame.manual_values['U1'],'maximum_c':95}),['U1'],{})
                    frame.therm_time_enabled.SetValue(True);frame.therm_time_duration.ChangeValue('20')
                    frame.therm_power_schedule.ChangeValue('{"U1":[[0,0],[1,1]]}')
                    self.exercise(frame,setup_file,Path(folder)/'thermal-inputs.json')
                    invalid=setup_file.capture(frame);invalid['component_inputs']['references']=['gone']
                    with self.assertRaises(ValueError):setup_file.validate(frame,invalid)
                finally:frame.Close();self.app.Yield()


if __name__=='__main__':unittest.main()
