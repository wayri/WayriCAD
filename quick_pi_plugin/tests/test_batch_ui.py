"""Native independent-case UI lifecycle and explicit Joule-feedback setup."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
try:
    import wx
    from quick_pi_plugin.batch_ui import BatchStudyDialog
    from quick_pi_plugin.electrothermal_ui import feedback_studies, ElectrothermalStudyDialog
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx=None
from quick_pi_plugin.batch import execute
from quick_pi_plugin.tests.test_batch import case,study
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.solver import solve


@unittest.skipIf(wx is None,'Native wxPython required')
class BatchUITests(unittest.TestCase):
    def setUp(self):
        self.app=wx.GetApp() or wx.App(False)
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'board.kicad_pcb'
        self.path.write_text('Synthetic IO boundary; solver uses analytical strip fixture')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest();self.dialogs=[]
        self.mesh,self.source,self.sink=strip(nx=4,ny=2)

    def tearDown(self):
        for dialog in self.dialogs:
            if not dialog._closed:
                (dialog.close if hasattr(dialog,'close') else dialog._close)()
        self.app.Yield();self.temp.cleanup()

    def wait(self,condition):
        deadline=time.monotonic()+10
        while not condition():
            self.app.Yield();time.sleep(.005)
            self.assertLess(time.monotonic(),deadline)
        self.app.Yield()

    def runner(self,request,cancel):
        def electrical(value):
            return {'result':solve(self.mesh,self.source,sinks=[{'id':'load','nodes':self.sink,
                'current_A':value['sinks'][0]['current_A']}],source_voltage=value['source_voltage'])}
        return execute(request,electrical)

    def dialog(self,runner=None):
        dialog=BatchStudyDialog(None,study(case('A'),case('B',2)),{'terminals':[]},
                               runner or self.runner,self.path,self.sha)
        self.dialogs.append(dialog);dialog.Show();self.app.Yield();return dialog

    def test_real_fem_independent_cases_show_results_then_edits_invalidate_export(self):
        dialog=self.dialog();dialog.SetSize((900,650));dialog.run_cases()
        self.wait(lambda:not dialog._busy)
        self.assertEqual(dialog.result['batch']['status'],'COMPLETED')
        self.assertIn('A · COMPLETED',dialog.details.GetValue())
        self.assertIn('B · COMPLETED',dialog.details.GetValue())
        self.assertTrue(dialog.export.IsEnabled())
        dialog.setup.SetValue(json.dumps(study(case('Changed'))));self.app.Yield()
        self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())

    def test_stale_board_and_cancel_do_not_accept_partial_batch(self):
        dialog=self.dialog();self.path.write_text('Changed');dialog.run_cases()
        self.assertIsNone(dialog.result);self.assertIn('changed',dialog.status.GetLabel())
        self.path.write_text('Synthetic IO boundary; solver uses analytical strip fixture')
        def runner(request,cancel):
            while not cancel():time.sleep(.005)
            raise InterruptedError('Cancelled')
        dialog.runner=runner;dialog.run_cases();dialog._cancel.set();self.wait(lambda:not dialog._busy)
        self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())

    def test_feedback_checkbox_dispatch_and_missing_physical_inputs_do_not_run(self):
        calls=[];frame=NS(joule_feedback=NS(GetValue=lambda:True),on_electrothermal=lambda **kw:calls.append(kw))
        QuickPIFrame.on_run(frame);self.assertEqual(calls,[{'feedback':True}])
        studies=feedback_studies(case()['electrical'])
        for key in ('ambient_c','copper_k_w_mk','dielectric_k_w_mk','board_h_w_m2k','board_emissivity'):
            self.assertIsNone(studies['steady']['thermal_settings'][key])
        jobs=[];dialog=ElectrothermalStudyDialog(None,studies,lambda *a:jobs.append(a),
            (FigureCanvasWxAgg,NavigationToolbar2WxAgg),self.path,self.sha,steady_only=True)
        self.dialogs.append(dialog);dialog.Show();self.app.Yield();dialog._run()
        self.assertFalse(jobs);self.assertFalse(dialog._busy);self.assertIsNone(dialog.result)
        self.assertIn('explicit',dialog.status.GetLabel());self.assertEqual(dialog.mode.GetCount(),1)


if __name__=='__main__':unittest.main()
