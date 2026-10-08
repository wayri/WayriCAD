"""Failure recovery must not leave a stale candidate available for Apply."""
import importlib
import os
import unittest
from unittest import mock
from test_sections import PACKAGE

errors=importlib.import_module(PACKAGE+'.error_handling')

class RecoveryTests(unittest.TestCase):
    def test_guidance_matches_failure_and_never_weakens_validation(self):
        cases={'Source changed after review':'Preview again','target lock exists':'Save and close',
               'Permission denied':'writable','kicad-cli executable missing':'matching kicad-cli',
               'rollback failed':'do not retry Apply','component parity failed':'Do not bypass'}
        for detail,expected in cases.items():
            with self.subTest(detail=detail):self.assertIn(expected,errors.recovery(detail))

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI')=='1','Opt-in native wx workflow')
class FailureGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx=wx;cls.app=wx.GetApp() or wx.App(False)
        cls.gui=importlib.import_module(PACKAGE+'.gui')
        cls.insertion=importlib.import_module(PACKAGE+'.insertion_gui')

    def test_native_error_dialog_has_selectable_details_and_copy_action(self):
        wx=self.wx
        def review(dialog):
            dialog.Show();wx.Yield()
            texts=[c for c in dialog.GetChildren() if isinstance(c,wx.TextCtrl)]
            self.assertEqual(texts[0].GetValue(),'Source changed after preview')
            self.assertGreater(texts[0].GetSize().height,100)
            self.assertTrue(any(isinstance(c,wx.Button) and c.GetLabel()=='Copy details' for c in dialog.GetChildren()))
            self.assertTrue(dialog.GetIcons().GetIcon(wx.Size(64,64)).IsOk())
            return wx.ID_OK
        with mock.patch.object(wx.Dialog,'ShowModal',review):errors.show_error(None,'Source changed after preview')
        wx.Yield()

    def test_failed_preflight_clears_prior_review_but_preserves_sources_and_issues(self):
        dialog=self.gui.FusionDialog()
        try:
            dialog.append_source('C:/Projects/Example/module.kicad_pro',alias='Module',variant='<Default>',variant_choices=['<Default>'])
            spec=dialog.options().sources[0]
            issue={'id':'source:missing','error':'Missing source resource','action':None}
            dialog.merge_issues=[(spec,{'issues':[issue]},issue)]
            dialog.issue_choices={'source:missing':'manual'}
            dialog.guided_started=True
            dialog.notebook.SetSelection(dialog.notebook.FindPage(dialog.review_page))
            dialog.guided_preview_ready=True;dialog.import_plan={'old':'candidate'}
            dialog.open_button.Enable();dialog.offline_button.Enable()
            with mock.patch.object(dialog,'visual_source_records',return_value=[]):
                dialog.done(False,None,'Source changed after review')
            self.assertFalse(dialog.guided_preview_ready);self.assertIsNone(dialog.import_plan)
            self.assertFalse(dialog.open_button.IsEnabled());self.assertFalse(dialog.offline_button.IsEnabled())
            self.assertEqual(dialog.grid.GetNumberRows(),1)
            self.assertEqual({i[2]['id'] for i in dialog.merge_issues},{'source:missing','merge:validation'})
            self.assertIn('Preview again',dialog.merge_issues[0][2]['error'])
            self.assertEqual(dialog.issue_choices['source:missing'],'manual')
            self.assertIn('Refresh preview',dialog.guide_next.GetLabel())
        finally:dialog.Destroy();self.wx.Yield()

    def test_failed_import_disables_old_apply_and_requires_fresh_review(self):
        dialog=self.insertion.InsertionDialog()
        try:
            dialog.plan={'old':'candidate'};dialog.plan_file='old.json';dialog.closed.SetValue(True)
            with mock.patch.object(errors,'show_error') as show:
                dialog.finish(mock.Mock(),None,'Target changed after preview')
            self.assertIsNone(dialog.plan);self.assertIsNone(dialog.plan_file)
            self.assertFalse(dialog.closed.GetValue());self.assertFalse(dialog.apply_button.IsEnabled())
            show.assert_called_once();self.assertFalse(dialog.busy)
        finally:dialog.Destroy();self.wx.Yield()

    def test_queued_worker_callbacks_are_ignored_after_window_destruction(self):
        for construct in (self.gui.FusionDialog,self.insertion.InsertionDialog):
            dialog=construct();queued=[];callback=mock.Mock()
            with mock.patch.object(self.wx,'CallAfter',side_effect=lambda call,*args:queued.append((call,args))):
                dialog.defer(callback,'late result')
            dialog.Destroy();self.wx.Yield()
            for call,args in queued:call(*args)
            callback.assert_not_called()
