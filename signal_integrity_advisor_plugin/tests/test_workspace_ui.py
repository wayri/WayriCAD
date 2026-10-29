"""Native viewport proportions and reversible Quick SI panel actions."""
import importlib.util
import copy
from pathlib import Path
import tempfile
import unittest


_app = None


@unittest.skipUnless(importlib.util.find_spec('wx') and importlib.util.find_spec('pcbnew'),'Native KiCad/wx required')
class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wx
        from .native_ui_fixture import board_fixture
        board_fixture()
        global _app
        cls.wx=wx;_app=wx.GetApp() or wx.App(False)

    def setUp(self):
        import pcbnew
        from .native_ui_fixture import copy_board_fixture
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import RoutePreview
        from signal_integrity_advisor_plugin.quick_ui import QuickSIPanel
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'example.kicad_pcb';copy_board_fixture(self.path);self.before=self.path.read_bytes()
        self.frame=self.wx.Frame(None,size=(1280,800))
        self.panel=QuickSIPanel(self.frame,pcbnew.LoadBoard(str(self.path)),RoutePreview,saved_board=True)
        layout=self.wx.BoxSizer(self.wx.VERTICAL);layout.Add(self.panel,1,self.wx.EXPAND);self.frame.SetSizer(layout)
        self.frame.Show();_app.Yield()

    def tearDown(self):
        self.frame.Destroy();_app.Yield()
        self.assertEqual(self.path.read_bytes(),self.before)

    def test_default_route_is_primary_at_normal_and_minimum_window_sizes(self):
        p=self.panel
        self.assertFalse(p.workspace_splitter.IsSplit());self.assertFalse(p.results_splitter.IsSplit())
        for size in ((1280,800),(980,700)):
            self.frame.SetSize(size);self.frame.Layout();_app.Yield()
            self.assertGreaterEqual(p.preview.GetSize().width,p.GetClientSize().width*.95)
            self.assertGreaterEqual(p.preview.GetSize().height,p.GetClientSize().height*.66)
            for control in (p.workspace.setup,p.setup_button,p.run_button,p.cancel_button,p.workspace.details,p.workspace.fit,p.workspace.pcb,p.workspace.files):
                self.assertTrue(control.IsShownOnScreen())
                self.assertTrue(control.GetParent().GetClientRect().Contains(control.GetRect()),control.GetLabel())

    def test_setup_details_focus_and_resize_preserve_inputs_and_results(self):
        from signal_integrity_advisor_plugin.setup_state import capture
        p=self.panel;state=copy.deepcopy(capture(p));report={'keep':'original evidence'};p.report=report
        p.workspace.toggle_setup(show=True);p.workspace.toggle_details(show=True);_app.Yield()
        self.assertTrue(p.inputs.IsShownOnScreen());self.assertTrue(p.results.IsShownOnScreen())
        self.assertGreaterEqual(p.preview.GetSize().width,p.GetClientSize().width*.66)
        p.workspace_splitter.SetSashPosition(300);p.results_splitter.SetSashPosition(p.results_splitter.GetSize().height-180)
        setup_width=p.workspace_splitter.GetSashPosition()
        p.workspace.focus_view();_app.Yield()
        self.assertFalse(p.workspace_splitter.IsSplit());self.assertFalse(p.results_splitter.IsSplit())
        p.workspace.focus_view();_app.Yield()
        self.assertTrue(p.workspace_splitter.IsSplit());self.assertTrue(p.results_splitter.IsSplit())
        self.assertAlmostEqual(p.workspace_splitter.GetSashPosition(),setup_width,delta=2)
        self.frame.SetSize((980,700));self.frame.Layout();_app.Yield()
        self.assertGreaterEqual(p.preview.GetSize().width,p.GetClientSize().width*.65)
        self.assertGreaterEqual(p.preview.GetSize().height,260)
        self.assertEqual(capture(p),state);self.assertIs(p.report,report)

    def test_fit_uses_actual_routed_geometry_extent(self):
        from signal_integrity_advisor_plugin.quick_si import analyze
        p=self.panel
        p.fields['net'].SetValue('DATA');p.net_changed(None)
        p.fields['start'].SetValue('U1.1');p.fields['end'].SetValue('J1.1')
        p.fields['z0_ohm'].ChangeValue('50');p.fields['epsilon_eff'].ChangeValue('3')
        values=p._inputs();report,path=analyze(p.board,'DATA','U1.1','J1.1',**values)
        p._show_report(report,path,values);p.workspace.fit_view();_app.Yield()
        bounds=p.preview.scene_bounds()
        self.assertGreater((bounds[2]-bounds[0])*p.preview.scale,p.preview.GetClientSize().width*.75)
        self.assertIs(p.report,report)

    def test_production_frame_header_fits_real_text_and_late_icons(self):
        from signal_integrity_advisor_plugin.signal_integrity_advisor_plugin import SignalIntegrityFrame
        frame=SignalIntegrityFrame(None,self.panel.board,saved_board=True)
        try:
            frame.SetSize((980,700));frame.Show();frame.Layout();_app.Yield()
            p=frame.quick_si
            for control in (p.workspace.setup,p.workspace.details,p.workspace.fit,p.workspace.focus,p.workspace.files,p.workspace.pcb):
                text_width=control.GetTextExtent(control.GetLabelText())[0]
                bitmap=control.GetBitmap()
                bitmap_width=bitmap.GetLogicalSize().width if bitmap.IsOk() else 0
                self.assertGreaterEqual(control.GetSize().width,text_width+bitmap_width+control.FromDIP(12 if bitmap_width else 6),control.GetLabel())
                self.assertTrue(control.GetParent().GetClientRect().Contains(control.GetRect()))
            p.workspace.focus_view();_app.Yield()
            control=p.workspace.focus
            self.assertGreaterEqual(control.GetSize().width,control.GetTextExtent(control.GetLabelText())[0]+control.GetBitmap().GetLogicalSize().width+control.FromDIP(12))
        finally:frame.Destroy();_app.Yield()


if __name__=='__main__':unittest.main()
