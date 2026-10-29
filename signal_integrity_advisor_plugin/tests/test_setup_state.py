"""Native setup buttons round-trip actual controls without changing the PCB."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


_app=None


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),'Native KiCad/wx required')
class SetupStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        from .native_ui_fixture import board_fixture
        board_fixture()
        global _app
        cls.wx=wx; _app=wx.GetApp() or wx.App(False)

    def setUp(self):
        import pcbnew
        from .native_ui_fixture import copy_board_fixture
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        from signal_integrity_advisor_plugin.tests.test_ibis_models import SAMPLE
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'board.kicad_pcb'; self.config=copy_board_fixture(self.path)
        self.before=self.path.read_bytes(); self.model=Path(self.temp.name)/'device.ibs'; self.model.write_text(SAMPLE)
        self.frame=self.wx.Frame(None,size=(1100,760))
        self.panel=QuickSIPanel(self.frame,pcbnew.LoadBoard(str(self.path)),RoutePreview,saved_board=True)
        self.panel.fields['net'].SetValue('DATA'); self.panel.net_changed(None)
        self.panel.fields['start'].SetValue('U1.1'); self.panel.fields['end'].SetValue('J1.1')
        self.panel.changed(None)

    def tearDown(self):
        self.frame.Destroy(); _app.Yield()
        self.assertEqual(self.before,self.path.read_bytes())

    def prepare(self):
        from signal_integrity_advisor_plugin.ibis_models import load_ibis,assignment_from_catalog
        panel=self.panel
        panel.fields['rise_ns'].ChangeValue('0.75'); panel.fields['z0_ohm'].ChangeValue('52')
        panel.fields['eye_load_pf'].ChangeValue('2.5')
        panel.fields['eye_via_l_nh'].ChangeValue('0.6')
        panel.fields['eye_via_c_pf'].ChangeValue('0.25')
        panel.eye_enabled.SetValue(True); panel.return_setup._use_suggested()
        panel.return_source.SetValue('U1.3'); panel.return_sink.SetValue('J1.3')
        panel.study_cases=copy.deepcopy(self.config['cases'])
        panel.crosstalk_pairs=[dict(id='pair',aggressor='data',victim='clock',rise_ns=1.,swing_v=1.,
            reference=dict(model='homogeneous-plane',layer='B.Cu',height_mm=.2,epsilon_r=4.))]
        panel.study_nets.Check(panel.study_nets.FindString('CLOCK'))
        catalog=load_ibis(self.model); pane=panel.ibis
        pane._catalogs[catalog['path']]=catalog; pane._current['source']=catalog
        pane._assignments[('DATA','source','U1.1')]=assignment_from_catalog(catalog,'DeviceA','5','DriveA','source','min')
        pane.set_context('DATA','U1.1','J1.1')

    def test_native_save_and_load_restore_all_editable_inputs(self):
        from signal_integrity_advisor_plugin.setup_state import capture
        self.prepare(); original=capture(self.panel)
        target=Path(self.temp.name)/'chosen.setup.json'
        controller=self.panel.project_setup
        with patch.object(controller,'_choose',return_value=str(target)):
            controller.on_save()
            self.assertTrue(target.is_file(),self.panel.status.GetLabel())
            self.panel.fields['net'].SetValue('CLOCK'); self.panel.net_changed(None)
            self.panel.fields['rise_ns'].ChangeValue('9'); self.panel.study_cases=[];self.panel.crosstalk_pairs=[]
            self.panel.ibis._assignments.clear();self.panel.ibis._catalogs.clear();self.panel.ibis._current=dict(source=None,sink=None)
            self.panel.report={'old':True};self.panel.study_report={'old':True}
            controller.on_load()
        self.assertIn('Loaded setup',self.panel.status.GetLabel())
        self.assertEqual(capture(self.panel),original)
        self.assertIsNone(self.panel.report);self.assertIsNone(self.panel.study_report)

    def test_invalid_net_or_changed_ibis_is_rejected_before_controls_change(self):
        from signal_integrity_advisor_plugin.setup_state import capture,validate
        self.prepare(); state=capture(self.panel)
        invalid=copy.deepcopy(state);invalid['fields']['start']='U99.7'
        with self.assertRaisesRegex(ValueError,'pad'):validate(self.panel,invalid)
        self.assertEqual(capture(self.panel),state)
        self.model.write_text(self.model.read_text()+'\n| changed\n')
        with self.assertRaisesRegex(ValueError,'changed'):validate(self.panel,state)
        self.assertEqual(capture(self.panel),state)

    def test_file_chooser_defaults_to_actual_board_project_and_cancel_is_noop(self):
        from signal_integrity_advisor_plugin.setup_state import capture
        before=capture(self.panel); dialog=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
        dialog.__enter__.return_value=dialog;dialog.ShowModal.return_value=self.wx.ID_CANCEL
        with patch('wx.FileDialog',return_value=dialog) as chooser:
            self.panel.project_setup.on_save()
            self.assertEqual(chooser.call_args.kwargs['defaultDir'],str(self.path.parent.resolve()))
            self.assertEqual(chooser.call_args.kwargs['defaultFile'],'board.quick-si.setup.json')
            self.panel.project_setup.on_load()
        self.assertEqual(capture(self.panel),before)

    def test_invalid_loaded_setup_keeps_existing_inputs_and_results(self):
        from signal_integrity_advisor_plugin.setup_state import capture
        from wayricad_runtime.project_setup import make_setup,save_setup
        self.prepare(); before=capture(self.panel); bad=copy.deepcopy(before)
        bad['fields']['net']='REMOVED_NET'
        target=Path(self.temp.name)/'invalid.setup.json'
        save_setup(target,make_setup('quick-si',self.path,bad))
        self.panel.report={'keep':'existing result'}
        with patch.object(self.panel.project_setup,'_choose',return_value=str(target)),patch('wx.MessageBox') as error:
            self.panel.project_setup.on_load()
        self.assertTrue(error.called)
        self.assertEqual(capture(self.panel),before)
        self.assertEqual(self.panel.report,{'keep':'existing result'})

    def test_model_changes_between_validation_and_restore_leave_prior_result(self):
        from signal_integrity_advisor_plugin.setup_state import capture,validate,restore
        self.prepare();before=capture(self.panel);checked=validate(self.panel,before)
        self.panel.report={'keep':'existing result'}
        self.model.write_text(self.model.read_text()+'\n| changed after validation\n')
        with self.assertRaisesRegex(ValueError,'changed'):restore(self.panel,checked)
        self.assertEqual(capture(self.panel),before)
        self.assertEqual(self.panel.report,{'keep':'existing result'})

    def test_pre_rlc_setup_loads_with_unreviewed_via_fields_blank(self):
        from signal_integrity_advisor_plugin.setup_state import capture,validate,restore
        self.prepare(); state=capture(self.panel)
        for key in ('eye_load_pf','eye_via_l_nh','eye_via_c_pf'):
            del state['fields'][key]
        checked=validate(self.panel,state)
        restore(self.panel,checked)
        for key in ('eye_load_pf','eye_via_l_nh','eye_via_c_pf'):
            self.assertEqual(self.panel.fields[key].GetValue(),'')


if __name__=='__main__':unittest.main()
