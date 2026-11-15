"""Shared Auto/Console/bundle contracts and native live-preview regressions."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quick_pi_plugin.series_workflow import checked_path, corrected_stage, stage_options
from quick_pi_plugin.tests.series_inference_fixture import inventory
from quick_pi_plugin.series_inference import reviewed_path
from wayricad_runtime.series_topology import infer_series_paths


def reviewed():
    board=inventory()
    proposal=infer_series_paths(board,'J1.1','J2.1')
    selections=[[dict(footprint_uuid=p['footprint_uuid'],model='100m',
                     from_pads=p['from_pads'],to_pads=p['to_pads'])
                 for p in stage['parts']] for stage in proposal['routes'][0]['stages']]
    return reviewed_path(proposal,0,selections,board)


class WorkflowContractTests(unittest.TestCase):
    def test_console_and_model_correction_preserve_reviewed_parallel_groups(self):
        from quick_pi_plugin.series_editor import display_path_command
        path=reviewed();before=deepcopy(path)
        command=display_path_command(path,inventory())
        restored=checked_path(path,inventory(),command)
        self.assertEqual(restored['branches'][0]['parallel'],path['branches'][0]['parallel'])
        corrected=corrected_stage(path,0,inventory(),'Q1','Q1-1','Q1-3','250m')
        self.assertEqual(corrected['branches'][0]['parallel'],path['branches'][0]['parallel'])
        self.assertEqual(corrected['branches'][0]['from_pads'],['Q1-1','Q1-2'])
        self.assertEqual(corrected['branches'][0]['model'],'250m')
        self.assertEqual(path,before)

    def test_pin_change_requires_replacement_confirmation_and_excludes_gates(self):
        path=reviewed()
        with self.assertRaisesRegex(ValueError,'Confirm'):
            corrected_stage(path,0,inventory(),'Q1','Q1-2','Q1-4','100m')
        changed=corrected_stage(path,0,inventory(),'Q1','Q1-2','Q1-4','100m',replace_groups=True)
        self.assertEqual(changed['branches'][0]['from_pads'],['Q1-2'])
        self.assertNotIn('parallel',changed['branches'][0])
        with self.assertRaises(ValueError):
            corrected_stage(path,0,inventory(),'Q1','Q1-5','Q1-3','100m',replace_groups=True)
        options=stage_options(path,0,inventory())
        self.assertTrue(all(not any(p.endswith('-5') for p in row['from_pads']+row['to_pads']) for row in options))

    def test_invalid_console_unknown_model_and_same_net_not_runnable(self):
        path=reviewed()
        for command in ('run pi J1.1 Q1:100m J2.1','run pi J1.1 J1.2','not a path'):
            with self.assertRaises(ValueError):checked_path(path,inventory(),command)
        with self.assertRaises(ValueError):
            corrected_stage(path,0,inventory(),'Q1','Q1-1','Q1-3','')


try:
    import wx
except ImportError:
    wx=None
_APP=None


@unittest.skipIf(wx is None,'Native wx runtime required')
class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        global _APP
        from quick_pi_plugin.series_editor import SeriesPathDialog
        _APP=wx.GetApp() or wx.App(False)
        self.parent=wx.Frame(None)
        self.editor=SeriesPathDialog(self.parent,inventory(),'Example.kicad_pcb')
        self.editor.dialog.Show()
        self.editor.source.SetStringSelection('J1.1')
        self.editor.sink.SetStringSelection('J2.1')
        self.editor._changed()
        wx.Yield()

    def tearDown(self):
        self.editor.dialog.Destroy();self.parent.Destroy();wx.Yield()

    def fill(self):
        for bank in self.editor.inference.controls:
            for part,check,text,incoming,outgoing in bank:
                text.SetValue('100m')
        wx.Yield()

    def test_auto_live_preview_compact_stages_and_invalid_model(self):
        editor=self.editor
        self.assertEqual(editor.workflow.book.GetPageCount(),3)
        self.assertTrue(editor.workflow.corrections.IsCollapsed())
        editor._infer();self.fill()
        self.assertIsNotNone(editor.workflow.current_path)
        self.assertEqual(editor.workflow.preview_book.GetPageText(0),'Diagram')
        self.assertEqual(editor.workflow.diagram.tree['status'],'topology_only')
        self.assertTrue(editor.workflow.diagram.tree['nodes'])
        diagram_height=editor.workflow.diagram.GetVirtualSize().height
        for node in editor.workflow.diagram.tree['nodes']:
            for key in ('voltage_V','current_A','loss_W','input_power_W','output_power_W'):
                self.assertIsNone(node.get(key))
        self.assertTrue(editor.run_button.IsEnabled())
        self.assertEqual(sum(p.IsShown() for p in editor.inference.stage_panels),1)
        editor.inference.stage_choice.SetSelection(1);editor.inference._stage_changed()
        self.assertTrue(editor.inference.stage_panels[1].IsShown())
        editor.inference.controls[0][0][2].SetValue('')
        wx.Yield()
        self.assertIsNone(editor.workflow.current_path)
        self.assertEqual(editor.workflow.diagram.tree,{'nodes':[]})
        self.assertLess(editor.workflow.diagram.GetVirtualSize().height,diagram_height)
        self.assertFalse(editor.run_button.IsEnabled())
        self.assertFalse(editor.save_button.IsEnabled())
        self.assertIn('preview cleared',editor.workflow.tree.GetItemText(editor.workflow.tree.GetRootItem()))

    def test_console_live_validation_no_stale_path_or_batch_case(self):
        editor=self.editor
        editor._restore_path(reviewed())
        editor.workflow.book.SetSelection(1);wx.Yield()
        self.assertTrue(editor.manual.GetValue())
        self.assertTrue(editor.run_button.IsEnabled())
        editor.manual.SetValue('run pi J1.1 Q1.1')
        wx.Yield()
        self.assertFalse(editor.run_button.IsEnabled())
        self.assertIsNone(editor.workflow.current_path)
        with patch('wx.MessageBox'):
            editor._run(None)
            with patch('quick_pi_plugin.series_power_tree_ui.show_series_power_tree') as popup:
                editor._power_tree(None)
                popup.assert_not_called()
        self.assertIsNone(editor.request)
        editor.batch_setup.add()
        self.assertEqual(editor.batch_setup.cases,[])
        self.assertTrue(editor._manual_pending)

    def test_bundle_edit_uses_same_workflow_and_preserves_models(self):
        editor=self.editor
        editor._restore_path(reviewed())
        editor.batch_setup.add()
        self.assertEqual(len(editor.batch_setup.cases),1)
        editor.batch_setup.select(SimpleNamespace(GetIndex=lambda:0))
        editor.workflow.book.SetSelection(2);wx.Yield()
        self.assertIsNotNone(editor.workflow.current_path)
        self.assertFalse(editor.run_button.IsEnabled())
        editor.batch_setup.edit()
        self.assertEqual(editor.workflow.book.GetSelection(),0)
        from quick_pi_plugin.series_editor import parse_saved_path
        self.assertEqual(parse_saved_path(editor.inference.reviewed_path(),editor.inventory)['series'],
                         parse_saved_path(reviewed(),editor.inventory)['series'])
        self.assertTrue(editor.run_button.IsEnabled())
        editor.source.SetStringSelection('J1.2')
        editor._changed(SimpleNamespace(GetEventObject=lambda:editor.source,Skip=lambda:None))
        self.assertIsNone(editor.inference.proposal)

    def test_stage_correction_dialog_validates_model_and_retains_parallel_bank(self):
        editor=self.editor
        editor._restore_path(reviewed())
        editor.list.SetSelection(0)

        def correct(dialog):
            fields=[c for c in dialog.GetChildren() if isinstance(c,wx.TextCtrl)]
            self.assertEqual(len(fields),1)
            fields[0].SetValue('not a model')
            self.assertFalse(dialog.FindWindow(wx.ID_OK).IsEnabled())
            fields[0].SetValue('250m')
            self.assertTrue(dialog.FindWindow(wx.ID_OK).IsEnabled())
            return wx.ID_OK

        with patch.object(wx.Dialog,'ShowModal',correct):
            editor.workflow.edit_stage()
        self.assertEqual(editor.branches[0]['model'],'250m')
        self.assertEqual(editor.branches[0]['parallel'],reviewed()['branches'][0]['parallel'])
        self.assertTrue(editor.run_button.IsEnabled())

    def test_mode_draft_roundtrip_and_cancel_do_not_run(self):
        from quick_pi_plugin.series_editor import SeriesPathDialog
        editor=self.editor
        editor._restore_path(reviewed())
        editor.workflow.book.SetSelection(1);wx.Yield()
        editor.manual.SetValue('run pi unfinished')
        wx.Yield()
        draft=editor.draft_snapshot()
        self.assertEqual(draft['editor']['workflow_mode'],1)
        restored=SeriesPathDialog(self.parent,inventory(),'Example.kicad_pcb',existing=draft)
        try:
            self.assertEqual(restored.workflow.book.GetSelection(),1)
            self.assertEqual(restored.manual.GetValue(),'run pi unfinished')
            self.assertFalse(restored.run_button.IsEnabled())
            self.assertIsNone(restored.request)
        finally:
            restored.dialog.Destroy()

    def test_auto_alternative_routes_revalidate_and_retain_review_inputs(self):
        from quick_pi_plugin.series_editor import SeriesPathDialog
        chosen=inventory()
        for number,net in enumerate(('VIN','OUT'),1):
            chosen['terminals'].append(dict(id=f'R1-{number}',label=f'R1.{number}',
                footprint_uuid='r1',reference='R1',net=net,component_value='100m'))
        self.editor.dialog.Destroy()
        self.editor=SeriesPathDialog(self.parent,chosen,'Example.kicad_pcb')
        editor=self.editor
        editor.source.SetStringSelection('J1.1');editor.sink.SetStringSelection('J2.1')
        editor._changed();editor._infer()
        self.assertEqual(editor.inference.routes.GetCount(),2)
        editor.inference.routes.SetSelection(1);editor.inference._populate()
        self.assertFalse(editor.run_button.IsEnabled())
        self.fill()
        expected=deepcopy(editor.workflow.current_path)
        editor.inference.routes.SetSelection(0);editor.inference._populate()
        editor.inference.routes.SetSelection(1);editor.inference._populate()
        self.assertEqual(editor.workflow.current_path,expected)

    def test_correct_selected_inferred_stage_applies_only_after_accept(self):
        editor=self.editor
        editor._infer();self.fill()
        editor.inference.stage_choice.SetSelection(1)
        before=deepcopy(editor.workflow.current_path)

        def cancel(dialog):
            field=next(c for c in dialog.GetChildren() if isinstance(c,wx.TextCtrl))
            field.SetValue('250m')
            return wx.ID_CANCEL

        with patch.object(wx.Dialog,'ShowModal',cancel):editor.workflow.edit_stage()
        self.assertEqual(editor.workflow.current_path,before)

        def accept(dialog):
            field=next(c for c in dialog.GetChildren() if isinstance(c,wx.TextCtrl))
            field.SetValue('250m')
            return wx.ID_OK

        with patch.object(wx.Dialog,'ShowModal',accept):editor.workflow.edit_stage()
        self.assertEqual(editor.branches[1]['model'],'250m')
        self.assertEqual(editor.branches[0]['model'],'100m')
        self.assertIsNone(editor.inference.proposal)

    def test_load_path_replaces_invalid_console_draft_and_restores_preview(self):
        import json
        import tempfile
        from pathlib import Path
        editor=self.editor
        editor.workflow.book.SetSelection(1);wx.Yield()
        editor.manual.SetValue('run pi unfinished');wx.Yield()
        with tempfile.TemporaryDirectory(prefix='series-load-') as root:
            source=Path(root)/'path.json'
            source.write_text(json.dumps(reviewed()),encoding='utf-8')
            with patch('wx.FileDialog') as choose:
                dialog=choose.return_value.__enter__.return_value
                dialog.ShowModal.return_value=wx.ID_OK
                dialog.GetPath.return_value=str(source)
                editor._load(None)
        self.assertEqual(editor.workflow.book.GetSelection(),0)
        from quick_pi_plugin.series_editor import parse_saved_path
        self.assertEqual(parse_saved_path(editor.workflow.current_path,editor.inventory),
                         parse_saved_path(reviewed(),editor.inventory))
        self.assertFalse(editor._manual_pending)
        self.assertTrue(editor.run_button.IsEnabled())


if __name__=='__main__':unittest.main()
