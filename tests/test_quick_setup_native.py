"""Real native setup handlers restore inputs without rerunning or editing a PCB."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
    from quick_therm_plugin.ui import QuickThermFrame
except ImportError:
    wx=None

_APP=None
_NATIVE_LOG=None
_PREVIOUS_LOG=None


@unittest.skipIf(wx is None,'KiCad native scientific GUI runtime required')
class QuickSetupNative(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _APP,_NATIVE_LOG,_PREVIOUS_LOG
        _APP=wx.GetApp() or wx.App(False)
        _NATIVE_LOG=wx.LogStderr();_PREVIOUS_LOG=wx.Log.SetActiveTarget(_NATIVE_LOG)
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

    def test_pi_saved_series_keeps_cross_net_endpoint_and_reopens_editor_draft(self):
        from quick_pi_plugin import setup_file
        from quick_pi_plugin.series_editor import draft_from_request,parse_saved_path
        from quick_pi_plugin.series_session import restore_endpoints
        rows=[dict(id=identifier,label=reference+'.'+str(pin),reference=reference,
                   footprint_uuid=reference,net=net)
              for identifier,reference,pin,net in [('s1','J1',1,'A'),('s2','J1',2,'A'),
                  ('a1','Q1',1,'A'),('a2','Q1',2,'A'),('b1','Q1',3,'B'),('b2','Q1',4,'B'),
                  ('gate','Q1',5,'G'),('e1','U1',1,'B'),('e2','U1',2,'B')]]
        path_data=dict(schema=1,source='J1.1',sink='U1.1',source_terminals=['s1','s2'],
                       sink_terminals=['e1','e2'],branches=[dict(reference='Q1',model='100m',
                       from_pad='a1',to_pad='b1',from_pads=['a1','a2'],to_pads=['b1','b2'])])
        with tempfile.TemporaryDirectory() as folder:
            board=Path(folder)/'example.kicad_pcb';pcbnew.SaveBoard(str(board),pcbnew.BOARD())
            with patch.object(QuickPIFrame,'_inspect'):
                frame=QuickPIFrame(None,board);self.app.Yield()
                try:
                    frame.inventory={'nets':['A','B','G'],'terminals':rows}
                    frame.net.Set(frame.inventory['nets']);frame.net.SetValue('A');frame._set_terminals()
                    frame.return_signal.Set(frame.inventory['nets']);frame.return_signal.SetStringSelection('A')
                    frame.return_nets.Set(frame.inventory['nets']);frame._return_nets_changed()
                    frame._series_request=parse_saved_path(path_data,frame.inventory)
                    frame._series_request['board_path']=frame.board_path
                    restore_endpoints(frame,frame._series_request)
                    frame._series_draft=draft_from_request(frame._series_request,frame.inventory)
                    frame._series_draft['editor']={'manual':'run pi J1.1 Q1.1 100m Q1.3 U1.1','manual_pending':False}
                    original=setup_file.capture(frame)
                    path=Path(folder)/'series-setup.json'
                    with patch('wx.FileDialog',return_value=self.dialog(path)),patch('wx.MessageBox') as warning:
                        frame.project_setup.on_save();warning.assert_not_called()
                    frame._series_request=None;frame._series_draft=None;frame._set_terminals()
                    with patch('wx.FileDialog',return_value=self.dialog(path)),patch('wx.MessageBox') as warning:
                        frame.project_setup.on_load();warning.assert_not_called()
                    self.assertEqual(setup_file.capture(frame),original)
                    request=frame._request('solve')
                    self.assertEqual(request['sink_terminals'],['e1','e2'])
                    self.assertEqual(request['series'][0]['from_pads'],['a1','a2'])
                    self.assertEqual(frame.sink.GetStringSelection(),'U1.1')
                    draft=frame._series_draft
                    fake=Mock();fake.show_with_draft.return_value=(None,draft)
                    with patch('quick_pi_plugin.series_editor.SeriesPathDialog',return_value=fake) as dialog:
                        frame.on_series_editor()
                        self.assertEqual(dialog.call_args.kwargs['existing'],draft)
                    self.assertEqual(frame._series_draft,draft)
                    from quick_pi_plugin.series_editor import SeriesPathDialog
                    editor=SeriesPathDialog(frame,frame.inventory,frame.board_path,existing=draft)
                    editor.dialog.Layout()
                    self.assertLessEqual(editor.dialog.GetSizer().CalcMin().height,
                                         editor.dialog.GetClientSize().height)
                    with patch.object(editor.dialog,'ShowModal',return_value=wx.ID_CANCEL):
                        parsed,kept=editor.show_with_draft()
                    self.assertIsNone(parsed)
                    self.assertEqual(kept['path'],draft['path'])
                finally:
                    frame.Destroy();self.app.Yield()

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
