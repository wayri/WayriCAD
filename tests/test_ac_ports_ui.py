"""Native optional UI checks; invoke explicitly with KiCad's Python."""
import time
import unittest
from types import SimpleNamespace

try:
    import wx
except ImportError:
    wx = None

from quick_pi_plugin.ac_ports_ui import create_frame, example_study


@unittest.skipIf(wx is None, 'Native wx runtime required')
class NativePortsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = create_frame()
        self.frame.Show()
        wx.Yield()

    def tearDown(self):
        if self.frame:
            self.frame.Close()
            wx.Yield()

    def test_minimum_size_controls_and_roundtrip(self):
        frame = self.frame
        frame.SetSize(frame.GetMinSize())
        frame.Layout()
        wx.Yield()
        panel = frame.tabs.GetParent()
        self.assertGreater(frame.tabs.GetSize().height, 100)
        self.assertLessEqual(frame.save_button.GetRect().GetBottom(), panel.GetClientSize().height)
        self.assertLessEqual(frame.save_button.GetRect().GetRight(), panel.GetClientSize().width)
        self.assertEqual(frame._collect()['ports'], example_study()['ports'])
        self.assertEqual(frame._collect()['frequencies_hz'], example_study()['frequencies_hz'])
        self.assertFalse(frame.save_button.IsEnabled())

    def test_real_worker_all_complex_entries_and_edit_invalidation(self):
        frame = self.frame
        frame.frequency_input.SetValue('1000')
        frame._run(None)
        deadline = time.monotonic()+10
        while frame.result is None and time.monotonic() < deadline:
            wx.Yield()
            time.sleep(.01)
        self.assertIsNotNone(frame.result, frame.status.GetLabel())
        self.assertEqual(frame.table.GetNumberCols(), 9)
        self.assertEqual(frame.table.GetNumberRows(), 1)
        self.assertEqual(len(frame.figure.axes), 4)
        self.assertEqual([len(axis.lines) for axis in frame.figure.axes], [1, 1, 1, 1])
        self.assertTrue(frame.save_button.IsEnabled())
        frame.fields['length_mm'].SetValue('11')
        wx.Yield()
        self.assertIsNone(frame.result)
        self.assertFalse(frame.save_button.IsEnabled())
        self.assertEqual(frame.table.GetNumberRows(), 0)
        frame._sort_table(SimpleNamespace(GetCol=lambda:0,Skip=lambda:None))
        self.assertEqual(frame.table.GetNumberRows(),0)

    def test_invalid_port_and_cancel_clear_results(self):
        frame = self.frame
        frame.port_controls[1][1].SetStringSelection('A')
        frame.port_controls[1][2].SetStringSelection('B')
        frame._run(None)
        self.assertIn('independent', frame.status.GetLabel())
        frame._cancel(None)
        self.assertIsNone(frame.result)
        frame._add(SimpleNamespace(Skip=lambda: None))
        self.assertEqual(frame.conductors.GetNumberRows(), 5)
        frame._remove(SimpleNamespace(Skip=lambda: None))
        self.assertEqual(frame.conductors.GetNumberRows(), 4)


if __name__ == '__main__':
    unittest.main()
