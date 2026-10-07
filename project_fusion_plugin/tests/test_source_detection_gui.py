"""Opt-in native source-picker auto scope and PCB-only dialog checks."""
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_sections import PACKAGE, SectionTests


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI')=='1','Opt-in native wx source detection')
class SourceDetectionGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx=wx;cls.app=wx.GetApp() or wx.App(False)
        cls.gui=importlib.import_module(PACKAGE+'.gui')
        cls.detection=importlib.import_module(PACKAGE+'.source_detection')

    def picker(self,path):
        result=mock.MagicMock();result.__enter__.return_value=result
        result.ShowModal.return_value=self.wx.ID_OK;result.GetPaths.return_value=[str(path)]
        return result

    def test_child_pick_resolves_project_and_selects_exact_second_occurrence(self):
        wx=self.wx
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spec,_=SectionTests().fixture(root)
            paths=self.detection.detect_source(root/'child.kicad_sch')[0].sheet_paths
            owner=mock.MagicMock();owner.__enter__.return_value=owner
            owner.ShowModal.return_value=wx.ID_OK;owner.GetSelection.return_value=1
            dialog=self.gui.FusionDialog()
            try:
                with mock.patch.object(wx,'FileDialog',return_value=self.picker(root/'child.kicad_sch')), \
                     mock.patch.object(wx,'SingleChoiceDialog',return_value=owner):
                    dialog.add(None)
                wx.Yield()
                self.assertEqual(dialog.grid.GetCellValue(0,0),spec.project)
                self.assertEqual(dialog.source_selector.selected_request()['sheet_paths'],[paths[1]])
                self.assertEqual(dialog.grid.GetCellValue(0,5),'Sheets')
                dialog.source_selector.whole.SetValue(True);dialog.source_selector.selected.SetValue(False)
                self.assertTrue(dialog.source_selector.selected_request()['whole_project'])
            finally:dialog.Destroy();wx.Yield()

    def test_board_only_pick_dispatches_dedicated_import_instead_of_project_merge(self):
        wx=self.wx
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'module.kicad_pcb';path.write_text('(kicad_pcb)')
            dialog=self.gui.FusionDialog()
            try:
                with mock.patch.object(wx,'FileDialog',return_value=self.picker(path)), \
                     mock.patch.object(dialog,'open_layout_import') as launch:
                    dialog.add(None)
                launch.assert_called_once_with(None,str(path.resolve()))
                self.assertEqual(dialog.grid.GetNumberRows(),0)
            finally:dialog.Destroy();wx.Yield()

    def test_layout_dialog_native_controls_and_busy_close_guard(self):
        module=importlib.import_module(PACKAGE+'.board_layout_gui')
        dialog=module.LayoutImportDialog(None)
        try:
            dialog.Show();self.wx.Yield()
            self.assertGreater(dialog.preview.GetClientSize().height,250)
            self.assertFalse(dialog.apply.IsEnabled())
            dialog.plan={'reviewed':True};dialog.plan_file=Path('C:/Projects/Example/layout-plan.json')
            insertion=importlib.import_module(PACKAGE+'.insertion_gui')
            with mock.patch.object(insertion.InsertionDialog,'python_launcher',return_value=Path('pythonw.exe')), \
                 mock.patch.object(module.subprocess,'Popen') as launch:
                dialog.apply_candidate(None)
            self.assertIn('--plan',launch.call_args.args[0])
            self.assertEqual(launch.call_args.args[0][-1],str(dialog.plan_file))
            dialog.busy=True
            event=mock.Mock();dialog.close(event)
            event.Skip.assert_not_called()
        finally:dialog.busy=False;dialog.Destroy();self.wx.Yield()
