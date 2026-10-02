"""Opt-in native responsive workflow, icons and stale review checks."""
import importlib,os,sys,unittest
import json,tempfile
from pathlib import Path
from types import ModuleType

ROOT=Path(__file__).resolve().parents[1]
if os.environ.get('FUSION_NATIVE_GUI')=='1':
    import wx
    package=ModuleType('_fusion_layout');package.__path__=[str(ROOT)];sys.modules[package.__name__]=package
    gui=importlib.import_module(package.__name__+'.gui')

@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI')=='1','Opt-in native wx workflow')
class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def test_responsive_workflow_icons_and_busy_guard(self):
        dialog=gui.FusionDialog()
        try:
            dialog.SetSize((960,720));dialog.Show();wx.Yield()
            self.assertEqual(dialog.notebook.GetPageCount(),4)
            self.assertIn(gui.VERSION,dialog.GetTitle())
            self.assertTrue(dialog.analyse_button.GetBitmap().IsOk())
            self.assertTrue(dialog.merge_button.GetBitmap().IsOk())
            for index,page in enumerate((dialog.controls_page,dialog.settings_page,dialog.tools_page)):
                dialog.notebook.SetSelection(index);dialog.Layout();page.Layout();page.FitInside();wx.Yield()
                self.assertLessEqual(page.GetVirtualSize().width,page.GetClientSize().width+2)
                self.assertTrue(page.IsEnabled())
            dialog.enable_inputs(False)
            self.assertTrue(all(not p.IsEnabled() for p in (dialog.controls_page,dialog.settings_page,dialog.tools_page)))
            dialog.enable_inputs(True)
        finally:dialog.Destroy();wx.Yield()

    def test_settings_change_clears_review_and_source_navigation(self):
        dialog=gui.FusionDialog()
        try:
            dialog.append_source('C:/Projects/Example/one.kicad_pro',alias='One',variant_choices=['<Default>'])
            dialog.preview.boxes=[('One',0,0,10,10)]
            dialog.mapping.InsertItem(0,'One')
            dialog.name.SetValue('Another output');wx.Yield()
            self.assertEqual(dialog.preview.boxes,[])
            self.assertEqual(dialog.mapping.GetItemCount(),0)
            dialog.preview.set_selected_alias('One');dialog.go_to_source(None)
            self.assertEqual(list(dialog.grid.GetSelectedRows()),[0])
            self.assertEqual(dialog.notebook.GetSelection(),0)
        finally:dialog.Destroy();wx.Yield()

    def test_mode_and_asset_toggle_invalidate_review_and_restore_offline_plan(self):
        dialog=gui.FusionDialog()
        try:
            self.assertFalse(dialog.import_current.GetValue())
            self.assertFalse(dialog.target_project.IsEnabled())
            self.assertTrue(dialog.copy_libraries.GetValue())
            dialog.import_plan={'old':'plan'}
            dialog.import_current.SetValue(True);dialog.mode_changed(None)
            self.assertIsNone(dialog.import_plan)
            self.assertTrue(dialog.target_project.IsEnabled())
            self.assertIn('Apply',dialog.merge_button.GetLabel())
            dialog.import_plan={'old':'plan'}
            event=wx.CommandEvent(wx.EVT_TOGGLEBUTTON.typeId,dialog.copy_libraries.GetId())
            dialog.copy_libraries.SetValue(False);dialog.copy_libraries.GetEventHandler().ProcessEvent(event)
            self.assertIsNone(dialog.import_plan)
            self.assertFalse(dialog.options().copy_assets)
            with tempfile.TemporaryDirectory() as temporary:
                plan={'workspace_mode':'import','target_project':'C:/Projects/Example/Target.kicad_pro',
                      'candidate_directory':temporary,'report':{'include_layout':False,'sources':[]},'copy_assets':False}
                path=Path(temporary)/'plan.json';path.write_text(json.dumps(plan))
                dialog.load_workspace_plan(path)
                self.assertEqual(dialog.import_plan,plan)
                self.assertFalse(dialog.target_closed.GetValue())
                self.assertFalse(dialog.copy_layout.GetValue())
                self.assertFalse(dialog.copy_libraries.GetValue())
                self.assertTrue(dialog.merge_button.IsEnabled())
                self.assertEqual(dialog.notebook.GetSelection(),3)
        finally:dialog.Destroy();wx.Yield()

if __name__=='__main__':unittest.main()
