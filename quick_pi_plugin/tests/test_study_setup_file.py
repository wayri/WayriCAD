"""Round-trip native advanced study inputs through the shared file actions."""
from pathlib import Path
import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    from quick_pi_plugin.plot_canvas import FigureCanvasWxAgg,NavigationToolbar2WxAgg
except ImportError:
    wx=None


@unittest.skipIf(wx is None,'Native wx/scientific runtime required')
class StudySetupFilesTests(unittest.TestCase):
    def setUp(self):
        self.app=wx.GetApp() or wx.App(False)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.board=Path(self.temp.name)/'board.kicad_pcb';self.board.write_text('Synthetic source identity, never edited')
        self.sha=hashlib.sha256(self.board.read_bytes()).hexdigest();self.dialogs=[]

    def tearDown(self):
        for dialog in self.dialogs:
            if getattr(dialog,'_preview_timer',None):dialog._preview_timer.Stop()
            dialog.Destroy()
        self.app.Yield()
        self.assertEqual(hashlib.sha256(self.board.read_bytes()).hexdigest(),self.sha)

    def factories(self):
        from quick_pi_plugin.ac_ui import ACStudyDialog
        from quick_pi_plugin.batch_ui import BatchStudyDialog
        from quick_pi_plugin.electrothermal_ui import ElectrothermalStudyDialog
        from quick_pi_plugin.transient_setup import PITransientStudyDialog
        from wayricad_runtime.transient_study_ui import TransientStudyDialog
        from quick_pi_plugin.decoupling.impedance_ui import PdnImpedanceDialog
        from quick_pi_plugin.tests.test_batch import study
        from quick_pi_plugin.tests.test_electrothermal import request as steady
        from quick_pi_plugin.tests.test_electrothermal_transient import request as transient
        canvas=(FigureCanvasWxAgg,NavigationToolbar2WxAgg);runner=lambda request,cancel:None
        root=Path(__file__).resolve().parents[2]
        pi=json.loads((root/'quick_pi_plugin/studies/transient-load-step.json').read_text())
        thermal=json.loads((root/'quick_therm_plugin/studies/transient-power-step.json').read_text())
        return [lambda:ACStudyDialog(None,runner,canvas,self.board,self.sha),
            lambda:BatchStudyDialog(None,study(),{'terminals':[]},runner,self.board,self.sha),
            lambda:ElectrothermalStudyDialog(None,{'steady':steady(),'transient':transient()},runner,canvas,self.board,self.sha),
            lambda:PITransientStudyDialog(None,'pi',pi,runner,canvas,self.board,self.sha),
            lambda:TransientStudyDialog(None,'thermal',thermal,runner,canvas,self.board,self.sha),
            lambda:PdnImpedanceDialog(None)]

    def test_every_native_study_handler_roundtrips_and_clears_results(self):
        from quick_pi_plugin.study_setup_file import add_study_setup,capture,validate
        for index,factory in enumerate(self.factories()):
            dialog=factory();self.dialogs.append(dialog)
            with self.subTest(dialog=type(dialog).__name__):
                if hasattr(dialog,'_banks'):
                    dialog._banks[0]=[dict(id='C8',capacitance_F=3e-6,esr_ohm=.02,esl_H=2e-9)]
                    dialog._rise_times[0]=1e-6;dialog._sync_bank_cells()
                if type(dialog).__name__=='ACStudyDialog':
                    dialog.quick_fields['width_mm'].ChangeValue('3.125');dialog._quick_dirty=True
                    dialog.setup_mode.SetSelection(0);dialog.conductors.SetCellValue(0,1,'0.125')
                if type(dialog).__name__=='ElectrothermalStudyDialog':
                    dialog.mode.SetSelection(1);dialog._reset()
                expected=capture(dialog);validate(dialog,expected)
                actions=add_study_setup(dialog,'quick-pi',self.board)
                path=Path(self.temp.name)/('study-'+str(index)+'.json')
                with patch.object(actions,'_choose',return_value=str(path)),patch('wx.MessageBox') as error:
                    actions.on_save();self.assertTrue(path.is_file(),dialog.status.GetLabel())
                    if hasattr(dialog,'fields'):next(iter(dialog.fields.values())).ChangeValue('999')
                    elif hasattr(dialog,'parameters'):next(iter(dialog.parameters.values())).ChangeValue('999')
                    else:dialog.setup.ChangeValue('{invalid draft')
                    dialog.result={'old':True}
                    actions.on_load()
                    self.assertFalse(error.called,error.call_args)
                self.assertEqual(capture(dialog),expected)
                self.assertIsNone(dialog.result)

    def test_wrong_mode_and_corrupt_tables_reject_without_partial_changes(self):
        from quick_pi_plugin.study_setup_file import capture,validate,add_study_setup
        dialog=self.factories()[0]();self.dialogs.append(dialog)
        original=capture(dialog);bad=copy.deepcopy(original);bad['mode']='pdn'
        with self.assertRaisesRegex(ValueError,'workflow'):validate(dialog,bad)
        bad=copy.deepcopy(original);bad['harmonics']=[['100']]
        with self.assertRaisesRegex(ValueError,'dimensions'):validate(dialog,bad)
        self.assertEqual(capture(dialog),original)
        actions=add_study_setup(dialog,'quick-pi',self.board)
        fake=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
        fake.__enter__.return_value=fake;fake.ShowModal.return_value=wx.ID_CANCEL
        with patch('wx.FileDialog',return_value=fake) as chooser:
            actions.on_save()
            self.assertEqual(chooser.call_args.kwargs['defaultDir'],str(self.board.parent.resolve()))
            self.assertEqual(chooser.call_args.kwargs['defaultFile'],'board.quick-pi.ac.setup.json')
        self.assertEqual(capture(dialog),original)


if __name__=='__main__':unittest.main()
