"""Native waveform sampling and stale-probe regressions."""
import unittest

try:
    import wx
    from signal_integrity_advisor_plugin.eye_ui import EyePanel
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'native wx runtime required')
class EyeProbeTests(unittest.TestCase):
    def test_probe_selects_sample_and_new_result_clears_stale_regions(self):
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        panel = EyePanel(frame)
        try:
            panel._plot_regions = [((0, 0, 100, 100), [0., 1., 2.],
                                    [[0., 2., 4.], [0., 3., 6.]], (0., 6.))]
            class Event:
                def GetX(self): return 60
                def GetY(self): return 51
                def Skip(self): pass
            panel.pin_probe(Event())
            self.assertEqual(panel.probes[0]['sample'], 1)
            self.assertEqual(panel.probes[0]['trace'], 1)
            self.assertEqual(panel.probes[0]['voltage_v'], 3.)
            panel.pin_probe(Event())
            self.assertEqual(len(panel.probes), 1)
            panel.show_result(None)
            panel.pin_probe(Event())
            self.assertEqual(panel.probes, [])
            self.assertIsNone(panel.hover)
        finally:
            frame.Destroy()
            app.ProcessPendingEvents()

    def test_filter_never_selects_first_search_match(self):
        from wayricad_runtime.net_filter import filter_combo
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        combo = wx.ComboBox(frame, choices=['CAN_P', 'DATA'], style=wx.CB_READONLY)
        try:
            combo.SetValue('DATA')
            filter_combo(combo, ['CAN_P', 'DATA'], 'can')
            # An existing exact net stays pinned; searching must not choose
            # the first matching net or silently change its IBIS assignment.
            self.assertEqual(combo.GetValue(), 'DATA')
            self.assertNotEqual(combo.GetValue(), 'CAN_P')
            self.assertNotEqual(combo.GetSelection(), wx.NOT_FOUND)
            combo.SetValue('CAN_P')
            filter_combo(combo, ['CAN_P', 'DATA'], ' CAN ')
            self.assertEqual(combo.GetValue(), 'CAN_P')
        finally:
            frame.Destroy()
            app.ProcessPendingEvents()
