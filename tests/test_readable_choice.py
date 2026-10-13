"""Native choice identity, popup sizing and tooltip regression checks."""
import sys
import unittest

try:
    import wx
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Requires native wxPython')
class ReadableChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        from wayricad_runtime.readable_choice import ReadableChoice, ReadableComboBox
        self.frame = wx.Frame(None, size=(700, 400))
        self.controls = [ReadableChoice(self.frame, size=(220, -1)),
                         ReadableComboBox(self.frame, style=wx.CB_READONLY, size=(220, -1))]
        self.long = '/Front output connectors/SLOT4_CH2_FORWARD_CLOCK_P'

    def tearDown(self):
        self.frame.Destroy()
        self.app.ProcessPendingEvents()

    def test_programmatic_population_and_selection_preserve_full_value(self):
        for control in self.controls:
            control.SetItems(['short', self.long])
            control.SetSelection(1)
            self.assertEqual(control.GetStringSelection(), self.long)
            self.assertEqual(control.GetToolTipText(), self.long)
            control.SetToolTip('Choose the routed net')
            self.assertEqual(control.GetToolTipText(), self.long + '\n\nChoose the routed net')
            control.Set(['replacement', self.long])
            control.SetStringSelection('replacement')
            self.assertEqual(control.GetToolTipText(), 'replacement\n\nChoose the routed net')
            control.Clear()
            self.assertEqual(control.GetToolTipText(), 'Choose the routed net')
            control.Append(self.long)
            control.SetSelection(0)
            self.assertIn(self.long, control.GetToolTipText())

    def test_editable_filter_value_is_shown_without_matching_an_item(self):
        from wayricad_runtime.readable_choice import ReadableComboBox
        control = ReadableComboBox(self.frame, choices=['VCC', 'GND'])
        control.SetValue('/Connector signals/*')
        self.assertEqual(control.GetToolTipText(), '/Connector signals/*')
        self.assertEqual(control.GetStrings(), ['VCC', 'GND'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows native popup API')
    def test_native_popup_is_wider_than_narrow_control(self):
        import ctypes
        from ctypes import wintypes
        send = ctypes.windll.user32.SendMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = ctypes.c_ssize_t
        for control in self.controls:
            control.Set([self.long])
            control.SetSelection(0)
            actual = send(control.GetHandle(), 0x015F, 0, 0)  # CB_GETDROPPEDWIDTH
            self.assertGreater(actual, control.GetSize().width)
            self.assertGreaterEqual(actual, control.GetTextExtent(self.long).width)
            self.assertEqual(control.GetStrings(), [self.long])

    def test_popup_width_is_bounded(self):
        from wayricad_runtime.readable_choice import popup_width
        self.assertEqual(popup_width([4000], 220, 1200), 1200)
        self.assertEqual(popup_width([20], 220, 1200), 220)


if __name__ == '__main__':
    unittest.main()
