"""Common geometric return review needs one confirmed domain, not pad mapping."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import wx
    import pcbnew
    from quick_pi_plugin.ui import QuickPIFrame
except ImportError:
    wx = None

_app = None


@unittest.skipIf(wx is None, 'KiCad native wx runtime required')
class ReturnReviewTests(unittest.TestCase):
    def setUp(self):
        global _app
        _app = wx.GetApp() or wx.App(False)
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'example.kicad_pcb'
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board
        portrait_board(self.path)
        with patch.object(QuickPIFrame, '_inspect'):
            self.frame = QuickPIFrame(None, str(self.path))
        f = self.frame
        f.inventory = {'nets': ['AGND', 'GND', 'VCC', 'VDD'], 'terminals': [
            {'id': 'source', 'label': 'J1.1', 'net': 'VCC'},
            {'id': 'load', 'label': 'U1.1', 'net': 'VCC'},
            {'id': 'ground-1', 'label': 'J1.2', 'net': 'GND'},
            {'id': 'ground-2', 'label': 'U1.2', 'net': 'GND'},
            {'id': 'ground-3', 'label': 'U1.2', 'net': 'GND'},
            {'id': 'analog', 'label': 'U2.2', 'net': 'AGND'}]}
        f.net.Set(f.inventory['nets']); f.net.SetValue('VCC')
        f.return_signal.Set(f.inventory['nets']); f.return_signal.SetStringSelection('VCC')
        f.return_nets.Set(f.inventory['nets']); f._return_nets_changed(); f._set_terminals()

    def tearDown(self):
        self.frame._end(); wx.CallLater(40, _app.ExitMainLoop); _app.MainLoop()
        self.directory.cleanup()

    def test_suggestion_requires_confirmation_and_advanced_stays_hidden(self):
        f = self.frame
        self.assertTrue(f.return_options.IsCollapsed())
        self.assertEqual(f._return_selected_nets(), [])
        self.assertFalse(f.return_run.IsEnabled())
        self.assertEqual(f._return_suggestion, 'GND')
        self.assertIn('suggestion', f.return_hint.GetLabel())
        f._return_use_suggestion()
        self.assertEqual(f._return_selected_nets(), ['GND'])
        self.assertTrue(f.return_run.IsEnabled())
        self.assertEqual(f.return_source.GetSelection(), 0)

    def test_common_review_needs_no_optional_return_pads(self):
        f = self.frame; f._return_use_suggestion()
        with patch.object(f, '_job') as run: f.on_return_path()
        request = run.call_args.args[0]
        self.assertEqual(request['signal_net'], 'VCC')
        self.assertEqual(request['return_nets'], ['GND'])
        self.assertEqual(request['sample_pitch_mm'], .25)
        self.assertEqual(request['return_via_radius_mm'], 2.)
        self.assertEqual(request['return_terminal_ids'], [])

    def test_multiple_returns_and_duplicate_pad_identities_survive(self):
        f = self.frame; f._return_use_suggestion()
        f.return_nets.Check(f.return_nets.FindString('AGND')); f._return_nets_changed()
        self.assertEqual(f._return_selected_nets(), ['AGND', 'GND'])
        self.assertIn('Multiple selected', f.return_primary.GetStringSelection())
        f.return_sink.SetStringSelection('U1.2 [ground-3]')
        with patch.object(f, '_job') as run: f.on_return_path()
        self.assertEqual(run.call_args.args[0]['return_terminal_roles'], {'load': 'ground-3'})

    def test_changed_signal_clears_old_optional_pads_and_results(self):
        f = self.frame; f._return_use_suggestion()
        f.return_source.SetStringSelection('J1.2'); f.return_bundle = {'return_path': {'old': True}}
        f.return_signal.SetStringSelection('VDD'); f._return_signal_changed()
        self.assertEqual(f.return_source.GetSelection(), 0)
        self.assertEqual(f.return_bundle, {})
        self.assertFalse(f.return_export.IsEnabled())
        f.return_signal.SetStringSelection('GND'); f._return_signal_changed()
        self.assertEqual(f._return_selected_nets(), [])
        self.assertFalse(f.return_run.IsEnabled())

    def test_follow_setup_can_be_overridden_and_restored(self):
        f = self.frame; f.net.SetValue('VDD'); f._set_terminals()
        self.assertEqual(f.return_signal.GetStringSelection(), 'VDD')
        f.return_signal.SetStringSelection('VCC')
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, f.return_signal.GetId())
        event.SetEventObject(f.return_signal); f._return_signal_changed(event)
        f._set_terminals(); self.assertEqual(f.return_signal.GetStringSelection(), 'VCC')
        f._return_use_current(); self.assertEqual(f.return_signal.GetStringSelection(), 'VDD')
