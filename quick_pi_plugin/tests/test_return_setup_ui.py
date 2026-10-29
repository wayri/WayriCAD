"""Guided DC return editing preserves identities, models and user confirmation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    from quick_pi_plugin.batch_ui import BatchStudyDialog
    from quick_pi_plugin.pi_return_setup import ReturnSetupDialog, choose_pad_unit
except ImportError:
    wx = None


def fixture():
    cases = [{'name': 'Main rail', 'electrical': {'net': '+5V', 'source_terminal': 'j1p',
              'source_voltage': 5., 'sinks': [{'terminal': 'u1p', 'current_A': 2.}]}},
             {'name': 'Logic rail', 'electrical': {'net': '+3V3', 'source_terminal': 'u2p',
              'source_voltage': 3.3, 'sinks': [{'terminal': 'u3p', 'current_A': .5}]}}]
    rows = [('j1p','J1.1','J1','+5V'),('u1p','U1.1','U1','+5V'),
            ('u2p','U2.1','U2','+3V3'),('u3p','U3.1','U3','+3V3'),
            ('j1g','J1.2','J1','GND'),('u1g1','U1.2','U1','GND'),
            ('u1g2','U1.3','U1','GND'),('u2g','U2.2','U2','GND'),
            ('u3g','U3.2','U3','GND'),('iso','J2.2','J2','ISO_GND')]
    inventory = {'nets': ['+5V','+3V3','GND','ISO_GND'], 'terminals': [
        {'id': identity, 'label': label, 'reference': ref, 'net': net}
        for identity, label, ref, net in rows]}
    return {'schema': 'wayricad.pi-batch/v1', 'cases': cases}, inventory


_app = None


@unittest.skipIf(wx is None, 'Native wxPython required')
class ReturnSetupTests(unittest.TestCase):
    def setUp(self):
        global _app
        _app = wx.GetApp() or wx.App(False)
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            if window: window.Destroy()
        wx.CallLater(30, _app.ExitMainLoop); _app.MainLoop()

    def editor(self, study=None, inventory=None, **options):
        base, inv = fixture(); editor = ReturnSetupDialog(None, study or base, inventory or inv, **options)
        self.windows.append(editor); return editor

    def test_suggestions_require_apply_and_support_multiple_load_ground_pads(self):
        original, inventory = fixture(); before = copy.deepcopy(original)
        editor = self.editor(original, inventory, case_names=['Main rail'])
        self.assertEqual(editor.net.GetStringSelection(), 'GND')
        self.assertEqual(editor.source_pads, []); self.assertEqual(editor.mappings, {})
        with self.assertRaises(ValueError): editor.build_study()
        editor._suggest()
        self.assertEqual(editor.source_pads, ['j1g'])
        self.assertEqual(editor.mappings[('Main rail','load-1')], ['u1g1','u1g2'])
        self.assertIsNone(editor.updated)
        result = editor.build_study()
        self.assertEqual(original, before)
        self.assertEqual(result['cases'][1], original['cases'][1])
        self.assertEqual(result['shared_returns'][0]['loads'][0]['terminals'], ['u1g1','u1g2'])
        self.assertEqual(result['cases'][0]['electrical']['sinks'][0]['current_A'], 2.)

    def test_changing_ground_domain_clears_stale_pad_units(self):
        editor = self.editor(case_names=['Main rail']); editor._suggest()
        editor.net.SetStringSelection('ISO_GND'); editor._net_changed()
        self.assertEqual(editor.source_pads, []); self.assertEqual(editor.mappings, {})
        with self.assertRaisesRegex(ValueError, 'supply-ground'): editor.build_study()

    def test_existing_group_edit_preserves_advanced_settings_and_other_cases(self):
        editor = self.editor(case_names=['Main rail']); editor._suggest(); initial = editor.build_study()
        initial['shared_returns'][0]['edge_mm'] = .12
        before = copy.deepcopy(initial)
        edited = self.editor(initial, group_index=0)
        edited.mappings[('Main rail','load-1')] = ['u1g2']
        result = edited.build_study()
        self.assertEqual(result['shared_returns'][0]['edge_mm'], .12)
        self.assertEqual(result['cases'][1], before['cases'][1]); self.assertEqual(initial, before)
        self.assertEqual(result['shared_returns'][0]['loads'][0]['terminals'], ['u1g2'])

    def test_editing_one_group_preserves_an_unrelated_return_domain(self):
        editor = self.editor(case_names=['Main rail']); editor._suggest(); initial = editor.build_study()
        initial['cases'][1]['electrical']['sinks'][0]['id'] = 'load-1'
        other = {'name':'Isolated ground','net':'ISO_GND','source_terminals':['ISO_SOURCE'],
                 'loads':[{'case':'Logic rail','sink':'load-1','terminals':['ISO_LOAD']}], 'edge_mm':.22}
        initial['shared_returns'].append(copy.deepcopy(other))
        edited = self.editor(initial, group_index=0)
        self.assertEqual([c['name'] for c in edited.available], ['Main rail'])
        edited.name.SetValue('Reviewed main ground'); result = edited.build_study()
        self.assertEqual(result['shared_returns'][1], other)
        self.assertEqual(result['cases'][1], initial['cases'][1])

    def test_default_window_fits_return_buttons_and_narrow_windows_scroll(self):
        editor = self.editor(case_names=['Main rail']); editor.Show(); editor.Layout(); wx.YieldIfNeeded()
        content = editor.net.GetParent()
        self.assertLessEqual(editor.source_button.GetRect().right, content.GetClientSize().width)
        self.assertLessEqual(editor.net.GetRect().right, content.GetClientSize().width)
        editor.SetSize((760,570)); editor.Layout(); wx.YieldIfNeeded()
        self.assertGreaterEqual(content.GetVirtualSize().width, content.GetClientSize().width)
        self.assertTrue(editor.apply.IsEnabled())

    def test_independent_loop_model_and_options_remain_independent(self):
        original, inventory = fixture()
        original['cases'][0]['return_conduction'] = {'net': 'GND', 'source_terminal': 'u1g1',
                                                    'sink_terminal': 'j1g', 'edge_mm': .18}
        editor = self.editor(original, inventory, independent_case='Main rail')
        self.assertFalse(editor.cases.IsEnabled())
        self.assertEqual(editor.table.GetItemCount(), 1)
        editor.mappings[('Main rail','load-1')] = ['u1g2']
        result = editor.build_study()
        self.assertNotIn('shared_returns', result)
        self.assertEqual(result['cases'][0]['return_conduction'], {
            'net': 'GND', 'source_terminal': 'u1g2', 'sink_terminal': 'j1g', 'edge_mm': .18})
        editor.net.SetStringSelection('ISO_GND'); editor._net_changed()
        self.assertEqual(editor.mappings, {})
        self.assertEqual(editor.source_pads, [])

    def test_shared_return_alias_resolves_but_duplicate_pad_in_one_unit_fails(self):
        editor = self.editor(case_names=['Main rail']); editor._suggest()
        editor.mappings[('Main rail','load-1')] = ['J1.2']
        configured = editor.build_study()['shared_returns'][0]
        self.assertEqual(configured['loads'][0]['terminals'], ['j1g'])
        self.assertEqual(configured['source_terminals'], ['j1g'])
        editor.mappings[('Main rail','load-1')] = ['J1.2','j1g']
        with self.assertRaisesRegex(ValueError, 'repeated'): editor.build_study()

    def test_picker_keeps_uuid_identity_for_duplicate_pad_numbers(self):
        original, inventory = fixture()
        inventory['terminals'].append({'id': 'u1g3', 'label': 'U1.2', 'reference': 'U1', 'net': 'GND'})
        with patch('quick_pi_plugin.pi_return_setup.choose_items', return_value=[2]) as picker:
            chosen = choose_pad_unit(None, inventory, 'GND', ['u1g3'])
        labels = picker.call_args.args[1]
        self.assertTrue(any('u1g3' in label for label in labels))
        self.assertEqual(chosen, [sorted([r for r in inventory['terminals'] if r['net']=='GND'],
            key=lambda r:(r['reference'].casefold(),r['label'].casefold(),r['id']))[2]['id']])
        self.assertEqual(picker.call_args.kwargs['checked'], [2])
        rows=sorted([r for r in inventory['terminals'] if r['net']=='GND'],
                    key=lambda r:(r['reference'].casefold(),r['label'].casefold(),r['id']))
        keys=picker.call_args.kwargs['group_keys']
        for row,key in zip(rows,keys):
            if not row.get('footprint_uuid'):
                self.assertEqual(key,(row['id'],'GND'))

    def test_default_summary_edit_and_removal_do_not_require_json(self):
        base, inventory = fixture(); editor = self.editor(case_names=['Main rail']); editor._suggest()
        configured = editor.build_study()
        with tempfile.TemporaryDirectory() as temporary:
            board = Path(temporary)/'example.kicad_pcb'; board.write_text('(kicad_pcb)')
            dialog = BatchStudyDialog(None, configured, inventory, None, board, 'fixture')
            self.windows.append(dialog)
            self.assertEqual(dialog.book.GetPageText(0), '1 · Rails and returns')
            self.assertEqual(dialog.case_table.GetItemCount(), 2); self.assertEqual(dialog.return_table.GetItemCount(), 1)
            self.assertIn('GND', dialog.case_table.GetItemText(0, 3))
            original_cases = copy.deepcopy(configured['cases'])
            with patch.object(wx, 'MessageBox', return_value=wx.YES): dialog.remove_selected_return()
            self.assertEqual(dialog.study()['cases'], original_cases)
            self.assertEqual(dialog.study()['shared_returns'], [])
            self.assertIsNone(dialog.result); self.assertFalse(dialog.export.IsEnabled())


if __name__ == '__main__': unittest.main()
