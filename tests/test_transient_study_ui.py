"""Native study editor, raw plots and input invalidation with real solvers."""
import json
from pathlib import Path
import time
import unittest

try:
    import wx
    from wayricad_runtime.transient_study_ui import TransientStudyDialog,read_study
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
except ImportError:
    wx=None

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipIf(wx is None,'native wx runtime required')
class TransientStudyUITests(unittest.TestCase):
    def test_native_edit_run_plot_and_stale_result_for_each_model(self):
        app=wx.GetApp() or wx.App(False)
        for kind,folder,example in [('pi','quick_pi_plugin','transient-load-step.json'),
                                    ('thermal','quick_therm_plugin','transient-power-step.json')]:
            with self.subTest(kind=kind):
                initial=json.loads((ROOT/folder/'studies'/example).read_text())
                initial['step_s']=initial['duration_s']/100
                from importlib import import_module
                execute=import_module(folder+'.service').execute
                calls=[]
                def runner(request,cancel):
                    calls.append(request);return execute(request)
                dialog=TransientStudyDialog(None,kind,initial,runner,(FigureCanvasWxAgg,NavigationToolbar2WxAgg))
                try:
                    dialog.Show();app.Yield()
                    self.assertEqual(dialog._request()['study'],initial)
                    capacity_column=6 if kind=='pi' else 5
                    dialog.rows.SetCellValue(0,capacity_column,'')
                    dialog._run()
                    self.assertIn('required',dialog.status.GetLabel())
                    self.assertEqual(calls,[])
                    dialog.rows.SetCellValue(0,capacity_column,str(initial['loads' if kind=='pi' else 'components'][0]['capacitance_F' if kind=='pi' else 'capacitance_J_K']))
                    dialog._run()
                    deadline=time.monotonic()+8.
                    while dialog._busy and time.monotonic()<deadline:app.Yield();time.sleep(.01)
                    self.assertFalse(dialog._busy)
                    self.assertIsNotNone(dialog.result)
                    self.assertTrue(dialog.export.IsEnabled())
                    self.assertEqual(len(dialog.figure.axes),2)
                    self.assertEqual(dialog.book.GetSelection(),1)
                    dialog.parameters['duration_s'].SetValue(str(initial['duration_s']*2));app.Yield()
                    self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())
                    self.assertFalse(dialog.figure.axes)
                    self.assertEqual(len(calls),1)
                finally:dialog.Destroy();app.Yield()


if __name__=='__main__':unittest.main()
