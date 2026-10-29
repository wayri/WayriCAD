"""Native board-first sizing, reversible panels and persistent file actions."""
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    import wx
    _NATIVE_LOG=wx.LogStderr()
    _PREVIOUS_LOG=wx.Log.SetActiveTarget(_NATIVE_LOG)
    from quick_therm_plugin.ui import QuickThermFrame
except ImportError:
    wx=None
_app=None


@unittest.skipIf(wx is None,'Native KiCad wx runtime required')
class ViewportFocusTests(unittest.TestCase):
    def setUp(self):
        global _app
        _app=wx.GetApp() or wx.App(False);_app.SetExitOnFrameDelete(False)
        path=Path(__file__).resolve().parents[1]/'examples/thermal-demo.kicad_pcb'
        self.original=path.read_bytes();self.path=path
        with patch.object(QuickThermFrame,'_inspect'):
            self.frame=QuickThermFrame(None,path);_app.Yield()
        self.frame.Maximize(False);self.frame.Show()

    def tearDown(self):
        self.frame.Close();_app.Yield()
        self.assertEqual(self.path.read_bytes(),self.original)

    def settle(self):
        self.frame.Layout();_app.Yield();self.frame.therm_board_page.Layout();_app.Yield()

    def setup_pane(self,visible):
        f=self.frame;f._toggle_thermal_pane(f.therm_setup_splitter,f._therm_input_page,f.therm_result_splitter,visible,340);self.settle()

    def details_pane(self,visible):
        f=self.frame;f._toggle_thermal_pane(f.therm_result_splitter,f.therm_visual_host,f.therm_inspector,visible,-340,True);self.settle()

    def test_default_majority_viewport_and_file_actions_at_both_sizes(self):
        f=self.frame
        for size in ((1280,800),(940,680)):
            f.SetSize(size);self.settle()
            self.assertEqual(f.book.GetSelection(),0)
            self.assertFalse(f.therm_setup_splitter.IsSplit());self.assertFalse(f.therm_result_splitter.IsSplit())
            self.assertGreaterEqual(f.therm_canvas.GetSize().width,f.GetClientSize().width*.9)
            self.assertGreaterEqual(f.therm_canvas.GetSize().height,f.GetClientSize().height*.5)
            self.assertTrue(f.therm_files_button.IsShownOnScreen());self.assertTrue(f.therm_run_header.IsShownOnScreen())
            self.assertTrue(f.project_setup.save.GetParent().IsShown() is False)
            self.assertFalse(f.therm_play.IsShownOnScreen());self.assertFalse(f.therm_result_time.IsShownOnScreen())
            self.assertEqual(f.therm_setup_toggle.GetValue(),f.therm_setup_splitter.IsSplit())
            self.assertEqual(f.therm_details_toggle.GetValue(),f.therm_result_splitter.IsSplit())
            self.assertLess(f.therm_details_toggle.GetSize().width,150)
        labels=[]
        with patch.object(f,'PopupMenu',side_effect=lambda menu:labels.extend(item.GetItemLabelText() for item in menu.GetMenuItems() if not item.IsSeparator())):
            f._thermal_files()
        self.assertEqual(labels,['Save setup…','Load setup…','Save simulation…','Load simulation…',
                                 'Export report…','Dissipation Sankey…','Export to Blender…'])

    def test_files_dispatches_result_exports_with_drawers_closed(self):
        f=self.frame
        f.thermal_bundle={'quick_therm':{'components':[]}}
        f.therm_export.Enable();f.therm_blender.Enable()
        def choose_exports(menu):
            for item in menu.GetMenuItems():
                if item.GetItemLabelText() in ('Export report…','Dissipation Sankey…','Export to Blender…'):
                    self.assertTrue(item.IsEnabled())
                    menu.ProcessEvent(wx.CommandEvent(wx.EVT_MENU.typeId,item.GetId()))
        with patch.object(f,'on_export_diagnostic') as report,patch.object(f,'on_thermal_sankey') as sankey, \
             patch.object(f,'on_blender') as blender,patch.object(f,'PopupMenu',side_effect=choose_exports):
            f._thermal_files()
        report.assert_called_once_with('quick_therm')
        sankey.assert_called_once();blender.assert_called_once()
        self.assertFalse(f.therm_setup_splitter.IsSplit())
        self.assertFalse(f.therm_result_splitter.IsSplit())

    def test_playback_row_appears_only_for_computed_frames(self):
        f=self.frame
        f.thermal_bundle={'thermal_network':{'transient':{'frames':[{'time_s':0},{'time_s':1}]}}}
        f.therm_result_time.Set(['Steady state','0 s','1 s']);f.therm_result_time.SetSelection(1)
        f._update_thermal_timeline();self.settle()
        self.assertTrue(f.therm_play.IsShownOnScreen());self.assertTrue(f.therm_result_time.IsShownOnScreen())
        f.thermal_bundle={};f._update_thermal_timeline();self.settle()
        self.assertFalse(f.therm_play.IsShownOnScreen());self.assertFalse(f.therm_result_time.IsShownOnScreen())

    def test_focus_restores_open_panels_and_their_dragged_widths(self):
        f=self.frame;f.SetSize((1440,900));self.settle();self.setup_pane(True);self.details_pane(True)
        f.therm_setup_splitter.SetSashPosition(365);f.therm_result_splitter.SetSashPosition(-320);self.settle()
        widths=(f._therm_input_page.GetSize().width,f.therm_inspector.GetSize().width)
        f.therm_focus.SetValue(True);f._thermal_focus();self.settle()
        self.assertFalse(f.therm_setup_splitter.IsSplit());self.assertFalse(f.therm_result_splitter.IsSplit())
        f.therm_focus.SetValue(False);f._thermal_focus();self.settle()
        self.assertTrue(f.therm_setup_splitter.IsSplit());self.assertTrue(f.therm_result_splitter.IsSplit())
        self.assertLessEqual(abs(f._therm_input_page.GetSize().width-widths[0]),5)
        self.assertLessEqual(abs(f.therm_inspector.GetSize().width-widths[1]),5)
        f.SetSize((940,680));self.settle()
        self.assertFalse(f.therm_result_splitter.IsSplit())
        self.assertGreaterEqual(f.therm_canvas.GetSize().width,500)

    def test_field_mapping_reveals_inputs_and_narrow_panels_take_turns(self):
        f=self.frame;f.SetSize((940,680));self.settle()
        f._show_field_mapping();self.settle()
        self.assertTrue(f.therm_setup_splitter.IsSplit());self.assertFalse(f.therm_fields_pane.IsCollapsed())
        self.details_pane(True)
        self.assertFalse(f.therm_setup_splitter.IsSplit());self.assertTrue(f.therm_result_splitter.IsSplit())
        self.setup_pane(True)
        self.assertTrue(f.therm_setup_splitter.IsSplit());self.assertFalse(f.therm_result_splitter.IsSplit())


if __name__=='__main__':unittest.main()
