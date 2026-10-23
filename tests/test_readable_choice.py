"""Native choice identity, popup sizing and tooltip regression checks."""
import sys
import unittest
from unittest.mock import patch

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

    def test_bulk_population_preserves_outer_freeze_and_native_client_data(self):
        for control in self.controls:
            data = [object(), object(), object()]
            control.Freeze()
            try:
                control.Set(['Z', 'A', 'Z'])
                for index, item in enumerate(data):
                    control.SetClientData(index, item)
                self.assertTrue(control.IsFrozen())
            finally:
                control.Thaw()
            self.assertFalse(control.IsFrozen())
            self.assertEqual(control.GetStrings(), ['Z', 'A', 'Z'])
            self.assertEqual([control.GetClientData(i) for i in range(3)], data)
            control.SetSelection(2)
            control.Set(['Z', 'A', 'Z'])
            self.assertEqual(control.GetSelection(), wx.NOT_FOUND)
            self.assertFalse(control.IsFrozen())

    def test_bulk_failure_restores_repainting(self):
        for control in self.controls:
            with self.assertRaises((TypeError, ValueError)):
                control.Set(['A'], [object(), object()])
            self.assertFalse(control.IsFrozen())

    def test_insert_delete_invalidate_search_and_width(self):
        for control in self.controls:
            control.Set(['short'])
            revision = control._items_revision
            control.Insert(self.long, 0)
            self.assertGreater(control._items_revision, revision)
            self.assertEqual(control.GetString(0), self.long)
            self.assertGreaterEqual(control._maximum_text_width(), control.GetTextExtent(self.long).width)
            revision = control._items_revision
            control.Delete(0)
            self.assertGreater(control._items_revision, revision)
            self.assertEqual(control.GetStrings(), ['short'])

    def test_resize_and_shared_controls_reuse_exact_measurements(self):
        from wayricad_runtime.readable_choice import _TEXT_WIDTHS
        _TEXT_WIDTHS.clear()
        items = ['WWWW', self.long, 'iiiiiiiiii']
        first, second = self.controls
        with patch.object(first, 'GetTextExtent', wraps=first.GetTextExtent) as measure:
            first.Set(items)
            first._maximum_text_width()
            initial = measure.call_count
            self.assertEqual(initial, len(items))
            for width in range(200, 220):
                first.SetSize((width, 30))
                first._popup_dirty = True
                first._update_popup()
            self.assertEqual(measure.call_count, initial)
        second.SetFont(first.GetFont())
        with patch.object(second, 'GetTextExtent', wraps=second.GetTextExtent) as measure:
            second.Set(items)
            self.assertEqual(second._maximum_text_width(), first._maximum_text_width())
            self.assertEqual(measure.call_count, 0)

    def test_font_change_remeasures_and_late_dpi_callback_is_destroy_safe(self):
        from wayricad_runtime.readable_choice import _TEXT_WIDTHS
        _TEXT_WIDTHS.clear()
        for control in self.controls:
            control.Set([self.long])
            original = control._maximum_text_width()
            font = wx.Font(control.GetFont())
            font.SetPointSize(font.GetPointSize() + 8)
            control.SetFont(font)
            self.assertGreater(control._maximum_text_width(), original)
        control = self.controls[0]
        control.Destroy()
        self.app.ProcessPendingEvents()
        control._refresh_popup_metrics()

    def test_sorted_control_keeps_native_order_and_data(self):
        from wayricad_runtime.readable_choice import ReadableChoice, ReadableComboBox
        for cls, native, style in [(ReadableChoice, wx.Choice, wx.CB_SORT),
                                    (ReadableComboBox, wx.ComboBox, wx.CB_SORT | wx.CB_READONLY)]:
            control = cls(self.frame, style=style)
            baseline = native(self.frame, style=style)
            labels = ['Z', 'a', 'Z', '/long/net']
            data = [object() for _ in labels]
            control.Set(labels)
            baseline.Set(labels)
            for index, item in enumerate(data):
                control.SetClientData(index, item)
                baseline.SetClientData(index, item)
            self.assertEqual(control.GetStrings(), baseline.GetStrings())
            self.assertEqual([control.GetClientData(i) for i in range(4)],
                             [baseline.GetClientData(i) for i in range(4)])
            self.assertEqual(control.GetSelection(), baseline.GetSelection())


if __name__ == '__main__':
    unittest.main()
