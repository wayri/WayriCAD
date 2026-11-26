"""Saved-source refresh and exact rule-area association regressions."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from quick_emerge_plugin.board_sync import BoardSync, area_index
from wayricad_runtime.editor_refresh import RevisionState, source_stamp


class Choice:
    def __init__(self, labels, selected):
        self.labels = list(labels)
        self.index = selected

    def GetSelection(self):
        return self.index

    def GetStringSelection(self):
        return self.labels[self.index] if self.index >= 0 else ''

    def SetSelection(self, index):
        self.index = index

    def FindString(self, name, exact):
        return self.labels.index(name) if name in self.labels else -1

    def Clear(self):
        self.labels = []
        self.index = -1


class NativeSavedRefreshTests(unittest.TestCase):
    def test_saved_coupon_rule_edit_clears_results_and_retains_region_identity(self):
        try:
            import wx
            from quick_emerge_plugin.region_service import extract_region, native_python
            from quick_emerge_plugin.ui import QuickEMergeFrame
        except ImportError as exc:
            self.skipTest(str(exc))
        try:
            native_python()
        except RuntimeError as exc:
            self.skipTest(str(exc))
        from shutil import copyfile
        from unittest.mock import patch
        app = wx.App.Get() or wx.App(False)
        with TemporaryDirectory() as directory:
            fixture = Path(__file__).with_name('fixtures')/'region_coupon.kicad_pcb'
            board = Path(directory)/fixture.name
            copyfile(fixture,board)
            frame = QuickEMergeFrame(board)
            try:
                frame._region_done(extract_region(board),None,None)
                chosen = frame.region_listing['areas'][frame.rule_area.GetSelection()]['id']
                frame.signal_net.SetStringSelection('SIGNAL')
                frame.reference_net.SetStringSelection('GND')
                frame.region_material_review.SetValue(True)
                frame.inputs['f_start_hz'].ChangeValue('4000000000')
                frame.result = {'reviewed':True}
                board.with_suffix('.kicad_dru').write_text('(version 1)')
                with patch.object(frame,'load_rule_areas',side_effect=lambda: frame._region_done(extract_region(board),None,None)) as reload:
                    frame.board_sync.watcher.poll()
                    self.assertIsNone(frame.result)
                    self.assertIsNone(frame.session.review)
                    self.assertFalse(frame.run_button.IsEnabled())
                    frame.board_sync.watcher.poll()
                    reload.assert_called_once()
                self.assertEqual(frame.region_listing['areas'][frame.rule_area.GetSelection()]['id'],chosen)
                self.assertEqual(frame.signal_net.GetStringSelection(),'SIGNAL')
                self.assertEqual(frame.reference_net.GetStringSelection(),'GND')
                self.assertEqual(float(frame.inputs['f_start_hz'].GetValue()),4e9)
                self.assertFalse(frame.region_material_review.GetValue())
            finally:
                frame.close(None)
                app.Yield()


class BoardSyncTests(unittest.TestCase):
    def test_saved_change_reorders_same_named_areas_and_removes_renamed_net(self):
        areas = [{'id':'aa','name':'RF'}, {'id':'bb','name':'RF'}]
        frame = SimpleNamespace(region_listing={'areas':areas},
            mode=Choice(['patch','line','region'],2), rule_area=Choice(['RF','RF'],1),
            signal_net=Choice(['Feed'],0), reference_net=Choice(['GND'],0),
            running=False, region_busy=True, region_cancel=Mock(), region_material_review=Mock(),
            invalidate=Mock(), SetStatusText=Mock(), load_rule_areas=Mock())
        sync = BoardSync.__new__(BoardSync)
        sync.frame = frame
        sync.invalidate()
        frame.invalidate.assert_called_once()
        frame.region_cancel.set.assert_called_once()
        frame.region_material_review.SetValue.assert_called_once_with(False)
        self.assertIsNone(frame.region_listing)
        sync.reload()
        frame.load_rule_areas.assert_called_once()
        frame.rule_area = Choice(['RF','RF'],1)
        frame.signal_net = Choice(['SIGNAL','feed'],0)
        frame.reference_net = Choice(['GND'],0)
        self.assertTrue(sync.restore_choices({'areas':areas[::-1]}))
        self.assertEqual(frame.rule_area.GetSelection(),0)
        self.assertEqual(frame.signal_net.GetSelection(),-1)
        self.assertEqual(frame.reference_net.GetStringSelection(),'GND')

    def test_inbound_requires_exactly_one_existing_unique_identity(self):
        areas = [{'id':'AA'}, {'id':'BB'}]
        self.assertEqual(area_index(areas, ['bb']),1)
        for ids in ([],['not-a-zone'],['AA','BB']):
            self.assertEqual(area_index(areas, ids),-1)
        self.assertEqual(area_index([areas[0],areas[0]], ['AA']),-1)

    def test_project_and_rule_changes_invalidate_before_reload(self):
        with TemporaryDirectory() as tmp:
            board = Path(tmp)/'coupon.kicad_pcb'
            board.write_text('fixture')
            state = RevisionState(source_stamp(board))
            for suffix in ('.kicad_pro','.kicad_dru','.kicad_pcb'):
                board.with_suffix(suffix).write_text('updated fixture')
                self.assertEqual(state.observe(source_stamp(board),ready=True,available=True),'invalidate')
                self.assertIsNone(state.observe(source_stamp(board),ready=False,available=True))
                self.assertEqual(state.observe(source_stamp(board),ready=True,available=True),'reload')

    def test_template_refresh_keeps_study_and_discards_running_result(self):
        process = Mock()
        process.poll.return_value = None
        frame = SimpleNamespace(region_listing=None, mode=Choice(['template'],0),
            session=SimpleNamespace(process=process), running=True, region_busy=False,
            rule_area=Mock(), signal_net=Mock(), reference_net=Mock(),
            invalidate=Mock(), SetStatusText=Mock(), load_rule_areas=Mock())
        sync = BoardSync.__new__(BoardSync)
        sync.frame = frame
        sync.invalidate()
        process.terminate.assert_called_once()
        self.assertTrue(sync.discard_run)
        sync.reload()
        frame.load_rule_areas.assert_not_called()
