"""Native simple-return selection, explicit confirmation and stale-input checks."""
from pathlib import Path
import hashlib
import importlib.util
import os
import tempfile
import unittest


_app = None


@unittest.skipUnless(importlib.util.find_spec('wx'), 'Native wxPython required')
class ReturnSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _app
        import wx
        cls.wx = wx; _app = wx.GetApp() or wx.App(False)

    def setUp(self):
        from signal_integrity_advisor_plugin.return_setup_ui import ReturnSetupPanel
        self.frame = self.wx.Frame(None, size=(390, 700)); self.events = []
        self.terminals = [
            {'id':'signal-u','label':'U1.1','reference':'U1','net':'DATA'},
            {'id':'signal-j','label':'J1.1','reference':'J1','net':'DATA'},
            {'id':'ground-u','label':'U1.2','reference':'U1','net':'GND'},
            {'id':'ground-j','label':'J1.2','reference':'J1','net':'GND'},
            {'id':'ground-dotted','label':'U2.A.1','reference':'U2','net':'GND'},
            {'id':'duplicate-a','label':'U1.3','reference':'U1','net':'GND'},
            {'id':'duplicate-b','label':'U1.3','reference':'U1','net':'GND'},
            {'id':'analog-u','label':'U1.4','reference':'U1','net':'AGND'}]
        self.panel = ReturnSetupPanel(self.frame, ['DATA','CLOCK','GND','AGND'], self.terminals,
            ['F.Cu','B.Cu'], lambda:self.events.append('changed'), lambda:self.frame.Layout())
        sizer = self.wx.BoxSizer(self.wx.VERTICAL); sizer.Add(self.panel, 1, self.wx.EXPAND|self.wx.ALL, 10)
        self.frame.SetSizer(sizer); self.frame.Show(); _app.Yield()
        self.panel.set_context('DATA','U1.1','J1.1')

    def tearDown(self):
        self.frame.Destroy(); self.wx.CallLater(20,_app.ExitMainLoop); _app.MainLoop()

    def event(self, control, event_type):
        event = self.wx.CommandEvent(event_type, control.GetId()); event.SetEventObject(control)
        control.GetEventHandler().ProcessEvent(event); _app.Yield()

    def test_suggestion_requires_confirmation_and_details_stay_collapsed(self):
        self.assertEqual(self.panel.selected_nets(), [])
        self.assertTrue(self.panel.more.IsCollapsed())
        self.assertIn('GND',self.panel.suggested.GetLabel())
        self.event(self.panel.use_suggestion,self.wx.wxEVT_BUTTON)
        self.assertEqual(self.panel.selected_nets(), ['GND'])
        self.assertEqual(self.panel.source.GetValue(), 'Not specified')
        self.assertTrue(self.events)

    def test_same_component_pads_first_without_assigning_a_pin(self):
        self.panel._use_suggested()
        self.assertTrue(self.panel.source.GetString(1).startswith('U1.'))
        self.assertEqual(self.panel.sink.GetString(1), 'J1.2')
        self.assertEqual(self.panel.source.GetValue(), 'Not specified')
        self.assertEqual(self.panel.sink.GetValue(), 'Not specified')
        from signal_integrity_advisor_plugin.return_setup_ui import reference_for_label
        self.assertEqual(reference_for_label(self.terminals,'U2.A.1'), 'U2')

    def test_multireturn_and_off_switch_have_one_canonical_selection(self):
        self.panel._use_suggested()
        index = self.panel.nets.FindString('AGND'); self.panel.nets.Check(index)
        self.event(self.panel.nets,self.wx.wxEVT_CHECKLISTBOX)
        self.assertEqual(set(self.panel.selected_nets()), {'GND','AGND'})
        self.assertIn('2 return nets',self.panel.summary.GetLabel())
        self.panel.primary.SetValue('No return-path check')
        self.event(self.panel.primary,self.wx.wxEVT_COMBOBOX)
        self.assertEqual(self.panel.selected_nets(), [])
        self.assertEqual(self.panel.source.GetCount(),1)

    def test_signal_change_cannot_remain_its_own_return(self):
        self.panel._use_suggested(); self.panel.source.SetValue('U1.2')
        self.panel.set_context('GND','U1.2','J1.2')
        self.assertEqual(self.panel.selected_nets(), [])
        self.assertEqual(self.panel.source.GetValue(), 'Not specified')
        self.assertEqual(self.panel.nets.FindString('GND'),self.wx.NOT_FOUND)

    def test_ambiguous_pad_labels_export_exact_ids(self):
        self.panel._use_suggested()
        display = next(text for text in self.panel.source.GetStrings() if 'duplicate-a' in text)
        self.panel.source.SetValue(display)
        self.assertEqual(self.panel.terminal_value(self.panel.source),'duplicate-a')
        self.panel.source.SetValue('U1.2')
        self.assertEqual(self.panel.terminal_value(self.panel.source),'U1.2')

    def test_endpoint_change_clears_only_its_optional_return_pin(self):
        self.panel._use_suggested(); self.panel.source.SetValue('U1.2');self.panel.sink.SetValue('J1.2')
        self.panel.set_context('DATA','U2.A.1','J1.1')
        self.assertEqual(self.panel.source.GetValue(),'Not specified')
        self.assertEqual(self.panel.sink.GetValue(),'J1.2')

    def test_unchanged_context_does_not_repopulate_controls(self):
        from unittest.mock import patch
        self.panel._use_suggested()
        with patch.object(self.panel.nets,'Set',wraps=self.panel.nets.Set) as reset:
            self.panel.set_context('DATA','U1.1','J1.1')
            reset.assert_not_called()


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'), 'Native KiCad/wx required')
class QuickSIReturnIntegrationTests(unittest.TestCase):
    def test_actual_panel_request_and_review_keep_the_board_unchanged(self):
        import pcbnew, wx
        from signal_integrity_advisor_plugin.tests.test_study_native import make_board
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        from signal_integrity_advisor_plugin.quick_si import analyze
        global _app
        _app = wx.GetApp() or wx.App(False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'example.kicad_pcb'; make_board(path); before = path.read_bytes()
            frame = wx.Frame(None, size=(1100,760)); panel = QuickSIPanel(frame,pcbnew.LoadBoard(str(path)),RoutePreview,saved_board=True)
            layout = wx.BoxSizer(wx.VERTICAL); layout.Add(panel,1,wx.EXPAND); frame.SetSizer(layout)
            try:
                frame.Show(); _app.Yield()
                panel.fields['net'].SetValue('DATA'); panel.net_changed(None)
                panel.fields['start'].SetValue('U1.1'); panel.fields['end'].SetValue('J1.1'); panel.changed(None)
                panel.fields['z0_ohm'].SetValue('50'); panel.fields['epsilon_eff'].SetValue('3')
                self.assertNotIn('return_nets',panel._inputs())
                panel.return_setup._use_suggested()
                self.assertEqual(panel._inputs()['return_nets'],['GND'])
                panel.return_source.SetValue('U1.3');panel.return_sink.SetValue('J1.3')
                values=panel._inputs(); self.assertEqual(values['return_terminal_roles'],{'source':'U1.3','load':'J1.3'})
                report,route=analyze(panel.board,'DATA','U1.1','J1.1','Auto',**values)
                self.assertIn('return_path',report)
                panel._show_report(report,route,values)
                capture=os.environ.get('SI_RETURN_CAPTURE')
                if capture:
                    frame.Layout(); _app.Yield()
                    panel.inputs.Scroll(0,0)
                    import ctypes
                    width,height=frame.GetClientSize()
                    bitmap=wx.Bitmap(width,height,24);memory=wx.MemoryDC(bitmap)
                    memory.SetBackground(wx.Brush(wx.WHITE));memory.Clear()
                    self.assertTrue(ctypes.windll.user32.PrintWindow(int(frame.GetHandle()),int(memory.GetHDC()),1))
                    memory.SelectObject(wx.NullBitmap);bitmap.SaveFile(capture,wx.BITMAP_TYPE_PNG)
                panel.study_cases=[{'id':'data','net':'DATA','inputs':dict(values)}]
                panel._apply_study_returns()
                self.assertEqual(panel.study_cases[0]['inputs']['return_nets'],['GND'])
                self.assertNotIn('return_terminal_roles',panel.study_cases[0]['inputs'])
                self.assertIsNone(panel.report)
                panel.report=report;panel.path=route;panel.export.Enable()
                panel.return_setup.primary.SetValue('No return-path check');panel.return_setup._primary_changed()
                self.assertIsNone(panel.report);self.assertFalse(panel.export.IsEnabled())
                self.assertEqual(path.read_bytes(),before)
            finally:
                frame.Destroy(); wx.CallLater(30,_app.ExitMainLoop); _app.MainLoop()


if __name__ == '__main__': unittest.main()
