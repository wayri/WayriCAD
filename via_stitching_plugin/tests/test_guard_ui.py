"""Native UI lifecycle checks using deterministic, nonblocking job receipts."""
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    import pcbnew as p
    import wx
except ImportError:
    p = wx = None


@unittest.skipIf(wx is None, 'Requires native KiCad/wxPython')
class GuardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.App.Get() or wx.App(False)
        with patch.object(p.ActionPlugin, 'register', lambda self: None):
            from via_stitching_plugin.via_stitching_plugin import ViaFrame
        cls.Frame = ViaFrame

    def setUp(self):
        from test_guard_stitching import GuardStitchingTests
        self.fixture = GuardStitchingTests(); self.fixture.setUp()
        self.jobs = []
        owner = self
        class Job:
            ready = False
            closed = False
            cancelled = False
            elapsed = .2
            def __init__(self, board, api, settings, **options):
                self.settings = dict(settings); self.options = options
                self.board = board
                owner.jobs.append(self)
            def done(self): return self.ready
            def cancel(self): self.cancelled = True
            def close(self): self.closed = True
            def result(self):
                from wayricad_runtime.routing import plan_stitching
                from wayricad_runtime.geometry import board_fingerprint
                vias, rejected = plan_stitching(self.board,p,self.settings)
                return dict(identity=dict(companions={}), snapshot_sha256='fixture',
                    source_fingerprint=board_fingerprint(self.board), rejected=rejected,
                    candidates=[dict(x=v.GetPosition().x,y=v.GetPosition().y,
                        diameter=v.GetWidth(p.F_Cu),drill=v.GetDrillValue(),net=v.GetNetname()) for v in vias])
        self.stub = patch('wayricad_runtime.routing_worker.start_job', Job)
        self.stub.start()
        self.frame = self.Frame(None,self.fixture.board)
        self.frame.mode.SetValue('Guard selected routes')
        self.frame.guard_nets.Check(self.frame.guard_nets.FindString('SIGNAL'))
        self.frame.require_target_zone.SetValue(False)
        self.frame.spacing.ChangeValue('3')
        self.frame.skip_parts.SetValue(False)
        self.frame._update_guard_controls()

    def tearDown(self):
        self.frame.on_close(wx.CloseEvent())
        self.frame.Destroy(); self.app.ProcessPendingEvents()
        self.stub.stop()

    def test_preview_returns_before_job_and_cancel_discards_late_result(self):
        self.frame.preview(None)
        job = self.jobs[-1]
        self.assertEqual(self.frame.preview_plan, [])
        self.assertTrue(self.frame.cancel_button.IsEnabled())
        self.assertFalse(self.frame.preview_button.IsEnabled())
        self.assertEqual(job.options['snapshot_mode'],'saved')
        self.frame.cancel_planning()
        self.assertTrue(job.cancelled and job.closed)
        job.ready = True
        self.frame._poll_preview(None)
        self.assertFalse(self.frame.commit_button.IsEnabled())
        self.assertEqual(self.frame.preview_plan, [])

    def test_completed_result_materializes_only_unattached_ground_vias(self):
        self.frame.preview(None)
        self.jobs[-1].ready = True
        self.frame._poll_preview(None)
        self.assertEqual(len(self.frame.preview_plan),22)
        self.assertTrue(all(v.GetNetname()=='GND' for v in self.frame.preview_plan))
        self.assertEqual(len(list(self.fixture.board.GetTracks())),2)
        self.assertTrue(self.frame.commit_button.IsEnabled())
        self.assertTrue(self.jobs[-1].closed)
        self.frame.guard_offset.ChangeValue('2')
        self.frame.on_config_changed(None)
        self.assertFalse(self.frame.commit_button.IsEnabled())
        self.assertFalse(self.frame.preview_plan)

    def test_guard_selection_does_not_overwrite_guard_net(self):
        self.fixture.signal.SetSelected()
        self.frame.on_selection_timer(None)
        self.assertEqual(self.frame.net_choice.GetValue(),'GND')
        self.frame.capture_guard_tracks()
        self.assertEqual(len(self.frame._guard_track_ids),1)
        self.assertEqual(self.frame.net_choice.GetValue(),'GND')

    def test_live_snapshot_is_explicit(self):
        self.frame.live_snapshot.SetValue(True)
        self.frame.preview(None)
        self.assertEqual(self.jobs[-1].options['snapshot_mode'],'live')

    def test_settings_change_cancels_pending_process(self):
        self.frame.preview(None)
        job = self.jobs[-1]
        self.frame.guard_offset.ChangeValue('1.5')
        self.frame.on_config_changed(None)
        self.assertTrue(job.cancelled and job.closed)
        self.assertFalse(self.frame.commit_button.IsEnabled())

    def test_disabled_auto_refresh_does_not_scan_dense_board_every_tick(self):
        self.frame.auto_refresh.SetValue(False)
        with patch.object(self.frame,'_selection_signature',return_value=()) as scan:
            self.frame.on_selection_timer(None)
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
