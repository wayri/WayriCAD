"""Native guided-flow, cancellation and variant-disposition interaction checks."""
import importlib
import os
from pathlib import Path
import unittest
from unittest import mock

from test_sections import PACKAGE, model


@unittest.skipUnless(os.environ.get('FUSION_NATIVE_GUI') == '1', 'Opt-in native wx workflow')
class GuidedImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.GetApp() or wx.App(False)
        cls.gui = importlib.import_module(PACKAGE + '.gui')
        cls.choices = importlib.import_module(PACKAGE + '.variant_import_gui')

    def test_variant_dialog_returns_independent_named_destination_and_base(self):
        spec = model.SourceSpec('C:/Projects/Example/module.kicad_pro', 'Module', variant='Production')
        with mock.patch.object(self.choices, 'detect_variants', return_value=['<Default>', 'Production']):
            dialog = self.choices.VariantImportDialog(None, spec, ['<Default>', 'Working'])
        try:
            dialog.Show(); self.wx.Yield()
            self.assertTrue(dialog.GetIcons().GetIcon(self.wx.Size(64, 64)).IsOk())
            dialog.mode.SetSelection(1); dialog.update_mode()
            self.assertTrue(dialog.target.IsEnabled())
            self.assertFalse(dialog.name.IsEnabled())
            dialog.target.SetStringSelection('Working')
            result = dialog.result()
            self.assertEqual((result.variant, result.variant_mode, result.destination_variant),
                             ('Production', 'merge', 'Working'))
            self.assertEqual(spec.variant_mode, 'base')
            dialog.mode.SetSelection(2); dialog.update_mode(); dialog.name.SetValue('Module-Production')
            self.assertEqual(dialog.result().destination_variant, 'Module-Production')
            dialog.name.SetValue('<Default>')
            with self.assertRaises(model.MergeError): dialog.result()
            dialog.mode.SetSelection(0); dialog.update_mode()
            self.assertEqual(dialog.result().destination_variant, '<Default>')
            self.assertGreater(dialog.explanation.GetClientSize().height, 40)
        finally:
            dialog.Destroy(); self.wx.Yield()

    def test_guided_flow_requires_variant_choice_then_advances_and_invalidates(self):
        dialog = self.gui.FusionDialog()
        try:
            dialog.Show(); self.wx.Yield()
            self.assertTrue(dialog.GetIcons().GetIcon(self.wx.Size(64, 64)).IsOk())
            dialog.guided_started = True
            dialog.append_source('C:/Projects/Example/module.kicad_pro', alias='Module',
                                 variant='<Default>', variant_choices=['<Default>'])
            result = model.SourceSpec('C:/Projects/Example/module.kicad_pro', 'Module',
                                      variant='<Default>', variant_mode='separate', destination_variant='Module-Base')
            with mock.patch.object(self.choices, 'choose_variant_import', return_value=None):
                dialog.guided_next()
            self.assertIs(dialog.notebook.GetCurrentPage(), dialog.controls_page)
            with mock.patch.object(self.choices, 'choose_variant_import', return_value=result):
                dialog.guided_next()
            self.assertIs(dialog.notebook.GetCurrentPage(), dialog.settings_page)
            saved = dialog.options().sources[0]
            self.assertEqual(saved.destination_variant, 'Module-Base')
            self.assertIn('Separate: Module-Base', dialog.variant_summary.GetLabel())
            dialog.replace_sources([saved], cached_variants=[['<Default>']])
            self.assertEqual(dialog.options().sources[0].variant_mode, 'separate')
            with mock.patch.object(dialog, 'start') as preview:
                dialog.guided_next()
                preview.assert_called_once_with(False)
            dialog.guided_preview_ready = True
            dialog.clear_results()
            self.assertFalse(dialog.guided_preview_ready)
            dialog.busy = True
            with mock.patch.object(dialog, 'start') as preview:
                dialog.guided_next(); preview.assert_not_called()
        finally:
            dialog.busy = False; dialog.Destroy(); self.wx.Yield()

    def test_advanced_source_actions_are_hidden_until_requested(self):
        dialog = self.gui.FusionDialog()
        try:
            self.assertTrue(dialog.secondary_source_actions)
            self.assertTrue(all(not button.IsShown() for button in dialog.secondary_source_actions))
            event = mock.Mock(); event.IsChecked.return_value = True
            dialog.toggle_source_actions(event)
            self.assertTrue(all(button.IsShown() for button in dialog.secondary_source_actions))
        finally:
            dialog.Destroy(); self.wx.Yield()
