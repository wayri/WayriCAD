"""Native live fanout previews stay read-only, current and component-scoped."""
import unittest
import time
from unittest.mock import patch
import test_connector_escape as fixture
try:
    import wx
except ImportError:
    wx=None

@unittest.skipIf(wx is None or fixture.p is None,'KiCad wxPython required')
class FanoutLivePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.GetApp() or wx.App(False)

    def setUp(self):
        with patch.object(fixture.p.ActionPlugin,'register'):
            from fanout_generator_plugin.fanout_generator_plugin import FanoutFrame
        self.fixture=fixture.ConnectorTests();self.fixture.setUp();self.fixture.connector()
        self.frame=FanoutFrame(None,self.fixture.board)
        self.frame.scope.SetValue('Reference wildcard');self.frame.ref.ChangeValue('J1')
        self.frame.pattern.SetValue('Connector edge');self.frame.add_vias.SetValue(False)
        self.frame._update_controls()

    def tearDown(self):
        self.frame.Destroy();self.app.ProcessPendingEvents()

    def test_live_changes_coalesce_and_invalidate_apply_immediately(self):
        self.frame.preview(None,silent=True)
        self.assertTrue(self.frame.commit_button.IsEnabled())
        with patch('fanout_generator_plugin.fanout_generator_plugin.wx.CallLater') as timer:
            self.frame.on_config_changed(None)
            self.assertFalse(self.frame.commit_button.IsEnabled())
            self.frame.on_config_changed(None)
            self.assertEqual(timer.call_count,2)
            timer.return_value.Stop.assert_called()
        self.frame._live_call=None

    def test_style_thumbnail_has_the_actual_accepted_component_routes(self):
        self.frame.preview(None,silent=True)
        self.assertEqual(len(self.frame.preview_plan),6)
        self.assertEqual(self.frame.style_component.GetValue(),'J1')
        self.assertEqual(self.frame.style_preview.lines,self.frame.geometry_preview.lines)
        self.assertIn('6 accepted escapes',self.frame.style_summary.GetLabel())
        self.assertTrue(self.frame.style_preview.compact)

    def test_settings_reuse_display_context_but_native_geometry_changes_reload(self):
        self.frame.preview(None,silent=True)
        with patch.object(self.frame.geometry_preview,'set_board',wraps=self.frame.geometry_preview.set_board) as extract:
            self.frame.length.ChangeValue('2')
            self.frame.preview(None,silent=True)
            extract.assert_not_called()
            fp=next(iter(self.fixture.board.GetFootprints()))
            fp.SetPosition(fixture.p.VECTOR2I(fixture.p.FromMM(1),fixture.p.FromMM(1)))
            self.frame.preview(None,silent=True)
            self.assertEqual(extract.call_count,1)

    def test_preview_does_not_refresh_or_modify_editor_copper(self):
        with patch.object(fixture.p,'Refresh') as refresh:
            before=len(list(self.fixture.board.GetTracks()))
            self.frame.preview(None,silent=True)
            refresh.assert_not_called()
            self.assertEqual(before,len(list(self.fixture.board.GetTracks())))

    def test_selection_change_replaces_existing_preview_and_schedules_new_one(self):
        self.frame.preview(None,silent=True)
        self.frame.scope.SetValue('Selected footprints')
        with patch.object(self.frame,'_selection_signature',return_value=(('J1',),())),patch.object(self.frame,'_schedule_live_preview') as schedule:
            self.frame._sync_selection()
            self.assertFalse(self.frame.preview_items)
            self.assertFalse(self.frame.commit_button.IsEnabled())
            schedule.assert_called_once()

    def test_whole_board_scope_requires_explicit_refresh(self):
        self.frame.scope.SetValue('All connector pads')
        with patch('fanout_generator_plugin.fanout_generator_plugin.wx.CallLater') as timer:
            self.frame._schedule_live_preview();timer.assert_not_called()
        self.assertIn('Whole-board scope',self.frame.status.GetLabel())

    def test_all_rejected_component_remains_visible_in_thumbnail(self):
        self.frame.clearance.ChangeValue('30')
        self.frame.preview(None,silent=True)
        self.assertFalse(self.frame.preview_plan)
        self.assertEqual(self.frame.style_component.GetValue(),'J1')
        self.assertTrue(self.frame.style_preview.focus_points)
        self.assertIn('0 accepted escapes',self.frame.style_summary.GetLabel())

    def test_live_timer_computes_current_selection_without_applying(self):
        self.frame.Show()
        self.frame.on_config_changed(None)
        deadline=time.monotonic()+5
        timers=[]
        def finish_when_ready():
            if (self.frame.preview_plan and not self.frame._preview_busy) or time.monotonic()>=deadline:
                # Exit after the current callback/idle work has unwound, rather
                # than assuming a fixed wall-clock delay means preview is done.
                wx.CallAfter(self.app.ExitMainLoop)
            else:timers.append(wx.CallLater(50,finish_when_ready))
        timers.append(wx.CallLater(50,finish_when_ready))
        try:self.app.MainLoop()
        finally:
            for timer in timers:timer.Stop()
        self.assertEqual(len(self.frame.preview_plan),6)
        self.assertTrue(self.frame.commit_button.IsEnabled())
        self.assertFalse(list(self.fixture.board.GetTracks()))

    def test_connector_style_event_loads_relevant_defaults(self):
        self.frame.add_vias.SetValue(True)
        self.frame.routing_mode.SetValue('Adaptive')
        event=wx.CommandEvent(wx.wxEVT_COMBOBOX,self.frame.pattern.GetId())
        event.SetEventObject(self.frame.pattern)
        self.frame.on_config_changed(event)
        self.assertFalse(self.frame.add_vias.GetValue())
        self.assertEqual(self.frame.routing_mode.GetValue(),'Fixed')

    def test_destroy_cancels_pending_preview(self):
        with patch('fanout_generator_plugin.fanout_generator_plugin.wx.CallLater') as timer:
            self.frame._schedule_live_preview()
            self.frame.Destroy();self.app.ProcessPendingEvents()
            timer.return_value.Stop.assert_called()
        self.frame=wx.Frame(None)

if __name__=='__main__':unittest.main()
