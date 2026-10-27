"""Native AC recipes, engineering units and clear invalidation behavior."""
from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quick_pi_plugin.tests import test_ac_workflow as _workflow
wx=_workflow.wx
result_bundle=_workflow.result_bundle


@unittest.skipIf(wx is None,'KiCad native wx runtime required')
class ACReadableUITests(unittest.TestCase):
    setUp=_workflow.ACNativeWorkflowTests.setUp
    tearDown=_workflow.ACNativeWorkflowTests.tearDown
    dialog=_workflow.ACNativeWorkflowTests.dialog
    wait_for=_workflow.ACNativeWorkflowTests.wait_for

    def test_default_setup_has_folded_details_and_unsolved_return_preview(self):
        dialog=self.dialog();dialog.Show()
        self.assertTrue(dialog.advanced.IsCollapsed())
        self.assertEqual(dialog.setup_mode.GetSelection(),0)
        self.wait_for(lambda:bool(dialog.preview_figure.axes))
        self.assertEqual(len(dialog.preview_figure.axes[0].patches),2)
        self.assertIsNone(dialog.result)
        self.assertFalse(dialog.export.IsEnabled())

    def test_run_uses_visible_quick_recipe_and_units_match_values(self):
        requests=[]
        def run(request,cancel):
            requests.append(request);bundle=result_bundle();bundle['study']=request['study'];return bundle
        dialog=self.dialog(run);dialog.Show();dialog.input_path='previous.json';dialog.input_sha='previous'
        dialog.quick_fields['width_mm'].SetValue('3');wx.Yield()
        self.assertIsNone(dialog.input_path)
        dialog._run();self.wait_for(lambda:not dialog._busy)
        self.assertEqual(requests[0]['study']['conductors'][0]['width_mm'],3)
        self.assertIn('mW',dialog.summary_values['total_loss_w'].GetLabel())
        self.assertEqual(dialog.plot_view.GetSelection(),2)
        self.assertEqual(float(dialog.table.GetItemText(0,0)),100)
        self.assertEqual(float(dialog.table.GetItemText(0,1)),5)
        self.assertEqual(float(dialog.table.GetItemText(0,2)),20)
        self.assertEqual(float(dialog.table.GetItemText(0,4)),5)
        dialog._select_harmonic(0)
        self.assertEqual([line.get_xdata()[0] for line in dialog._focus],[100000,100000])
        dialog.quick_fields['ripple_rms_a'].SetValue('2');wx.Yield()
        self.assertIsNone(dialog.result);self.assertFalse(dialog.export.IsEnabled())
        self.assertEqual(dialog.summary_values['total_loss_w'].GetLabel(),'—')

    def test_custom_geometry_is_not_overwritten_by_quick_recipe(self):
        requests=[]
        def run(request,cancel):
            requests.append(request);bundle=result_bundle();bundle['study']=request['study'];return bundle
        dialog=self.dialog(run);dialog.Show()
        dialog.conductors.SetCellValue(0,3,'4')
        dialog._changed(Namespace(GetEventObject=lambda:dialog.conductors,Skip=lambda:None))
        self.assertEqual(dialog.setup_mode.GetSelection(),1)
        dialog._run();self.wait_for(lambda:not dialog._busy)
        self.assertEqual(requests[0]['study']['conductors'][0]['width_mm'],4)
        dialog._mode_changed();self.assertFalse(dialog.advanced.IsCollapsed())
        dialog.SetSize((900,700));dialog.Layout();wx.Yield()
        self.assertGreater(dialog.book.GetPage(0).GetVirtualSize().height,dialog.book.GetPage(0).GetClientSize().height)
        self.assertTrue(dialog.result_split.IsSplit())

    def test_imported_custom_study_opens_details_and_keeps_file_binding(self):
        requests=[]
        def run(request,cancel):
            requests.append(request);bundle=result_bundle();bundle['study']=request['study'];return bundle
        dialog=self.dialog(run);dialog.Show()
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'study.json';study=result_bundle()['study'];study['conductors'][0]['width_mm']=4
            source.write_text(json.dumps(study))
            with patch('quick_pi_plugin.ac_ui.wx.FileDialog') as choose:
                choose.return_value.__enter__.return_value.ShowModal.return_value=wx.ID_OK
                choose.return_value.__enter__.return_value.GetPath.return_value=str(source)
                dialog._load()
            self.assertEqual(dialog.setup_mode.GetSelection(),1)
            self.assertFalse(dialog.advanced.IsCollapsed())
            dialog._run();self.wait_for(lambda:not dialog._busy)
            self.assertEqual(requests[0]['study']['conductors'][0]['width_mm'],4)
            self.assertEqual(requests[0]['study_input_path'],str(source))


if __name__=='__main__':unittest.main()
