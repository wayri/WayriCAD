"""First inventory delivery must not duplicate scene work or leave wx frozen."""
import hashlib
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


@unittest.skipIf(wx is None, 'KiCad native wx runtime required')
class InventoryStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        from quick_pi_plugin.tests.test_workspace_ui import portrait_board
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'public-example.kicad_pcb'
        portrait_board(self.path)
        with patch.object(QuickPIFrame, '_inspect'):
            self.frame = QuickPIFrame(None, str(self.path))
            wx.Yield()

    def tearDown(self):
        self.frame._end(); wx.Yield()
        self.directory.cleanup()

    def inventory(self):
        return {'nets': ['GND', *[f'VCC_{index:04d}' for index in range(1373)]],
                'terminals': [{'id': f'pad-{i}', 'label': f'U1.{i}', 'net': 'VCC_0000'} for i in range(1, 5)],
                'source_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(), 'layers': []}

    def callback(self):
        with patch.object(self.frame, '_job') as job:
            self.frame._inspect()
        request, callback, _message = job.call_args.args
        self.assertEqual(request, {'action': 'inspect', 'board_path': str(self.path.resolve())})
        return callback

    def test_inventory_is_complete_and_scene_extraction_waits_for_geometry(self):
        callback = self.callback()
        inventory = self.inventory()
        with patch('quick_pi_plugin.ui.wx.CallAfter') as queued:
            callback(inventory)
            queued.assert_called_once_with(self.frame.preview_geometry)
        self.assertFalse(self.frame.main_panel.IsFrozen())
        self.assertEqual(self.frame.net.GetCount(), 1374)
        self.assertEqual(self.frame.return_signal.GetCount(), 1374)
        self.assertEqual(self.frame.return_nets.GetCount(), 1374)
        self.assertEqual(self.frame.source.GetItems(), ['U1.1', 'U1.2', 'U1.3', 'U1.4'])
        self.assertEqual(self.frame.source.GetSelection(), 0)
        self.assertEqual(self.frame.sink.GetSelection(), 1)
        self.assertEqual(self.frame.net.GetValue(), 'VCC_0000')
        self.assertEqual(self.frame._board_scene['primitives'], [])
        self.assertEqual(self.frame._board_scene_hash, inventory['source_sha256'])
        request = self.frame._request('geometry')
        self.assertEqual(request['net'], 'VCC_0000')
        self.assertEqual(request['source_terminal'], 'pad-1')
        self.assertEqual(request['sinks'], [{'terminal': 'pad-2'}])
        self.assertEqual(self.frame._request('solve')['sinks'], [{'terminal': 'pad-2', 'current_A': 1.0}])

    def test_failed_inventory_update_always_thaws_window(self):
        callback = self.callback()
        with patch.object(self.frame.net, 'Set', side_effect=RuntimeError('Native control rejected items.')):
            with self.assertRaisesRegex(RuntimeError, 'rejected items'):
                callback(self.inventory())
        self.assertFalse(self.frame.main_panel.IsFrozen())


if __name__ == '__main__':
    unittest.main()
