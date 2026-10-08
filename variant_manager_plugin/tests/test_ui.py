"""Opt-in native wx interaction, preview and layout checks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('VARIANT_NATIVE_UI') == '1', 'Opt-in KiCad wx native window')
class NativeUI(unittest.TestCase):
    def test_failed_tasks_preserve_review_and_ignore_obsolete_results(self):
        import wx
        from concurrent.futures import Future
        from types import SimpleNamespace
        from unittest.mock import patch
        from variant_manager_plugin.wayri_variants.gui import VariantFrame
        app = wx.GetApp() or wx.App(False)
        frame = VariantFrame()
        frame.pool.shutdown(wait=False)
        futures = []
        class ControlledPool:
            def submit(self, work):
                future = Future()
                futures.append(future)
                return future
            def shutdown(self, **kwargs):
                pass
        frame.pool = ControlledPool()
        previous = SimpleNamespace(count=1, operation='batch')
        frame.plan = previous
        frame.operations = [{'op': 'create', 'name': 'Production'}]
        try:
            with patch('wx.MessageBox') as message:
                frame.task('Stage', lambda: None, lambda result: None)
                futures[-1].set_exception(ValueError('Invalid candidate'))
                app.Yield()
                self.assertIs(frame.plan, previous)
                self.assertEqual(frame.operations[0]['name'], 'Production')
                self.assertTrue(frame.apply_button.IsEnabled())
                self.assertIn('previous staged review is retained', frame.review.GetValue())
                frame.task('Apply', lambda: None, lambda result: None, recover_plan=False)
                futures[-1].set_exception(ValueError('Source changed'))
                app.Yield()
                self.assertIs(frame.plan, previous)
                self.assertFalse(frame.apply_button.IsEnabled())
                self.assertIn('Reload', frame.review.GetValue())
                frame.review_stale = False  # Isolate source mismatch from the prior Apply failure.
                frame.inventory = {'names': ['Production'], 'objects': [], 'source_hashes': {'board': 'old'}}
                with patch('variant_manager_plugin.wayri_variants.gui.OperationDialog') as dialog:
                    dialog.return_value.__enter__.return_value.ShowModal.return_value = wx.ID_OK
                    dialog.return_value.__enter__.return_value.operations.return_value = [{'op': 'create', 'name': 'Prototype'}]
                    previous.names_after = ['Production']
                    frame.ack.SetValue(True)
                    frame.stage('create')
                    futures[-1].set_result(SimpleNamespace(expected={'board': 'new'}))
                    app.Yield()
                    self.assertIs(frame.plan, previous)
                    self.assertIn('Saved source changed since loading', frame.review.GetValue())
                    self.assertFalse(frame.apply_button.IsEnabled())
                    self.assertFalse(frame.ack.GetValue())
                    frame.task('Another invalid stage', lambda: None, lambda result: None)
                    futures[-1].set_exception(ValueError('Invalid name'))
                    app.Yield()
                    self.assertFalse(frame.apply_button.IsEnabled())
                    count = len(futures)
                    frame.apply(None)
                    self.assertEqual(len(futures), count)
                with tempfile.TemporaryDirectory() as temp:
                    destination = Path(temp) / 'review.json'
                    destination.mkdir()
                    previous.context = SimpleNamespace(home=Path(temp))
                    previous.expected = {}
                    with patch('wx.FileDialog') as dialog, patch('variant_manager_plugin.wayri_variants.gui.S.review', return_value={'rows': []}):
                        dialog.return_value.__enter__.return_value.ShowModal.return_value = wx.ID_OK
                        dialog.return_value.__enter__.return_value.GetPath.return_value = str(destination)
                        frame.export(None)
                    self.assertIs(frame.plan, previous)
                    self.assertIn('writable output', message.call_args.args[0])
                completed = []
                frame.task('Load', lambda: None, completed.append)
                frame.project_changed(None)
                futures[-1].set_result('old project')
                app.Yield()
                self.assertEqual(completed, [])
                self.assertIsNone(frame.inventory)
                self.assertEqual(frame.geometry, [])
                frame.inventory = {'names': [], 'objects': []}
                frame.reload()
                futures[-1].set_exception(OSError('Project unavailable'))
                app.Yield()
                self.assertIsNone(frame.inventory)
                frame.plan = SimpleNamespace(operation='restore')
                frame.stage('create')
                self.assertIn('clear the staged restore', message.call_args.args[0])
                frame.task('Closing', lambda: None, completed.append)
                frame.Close()
                app.Yield()
                futures[-1].set_result('closed window')
                app.Yield()
                self.assertEqual(completed, [])
        finally:
            if not frame.closed:
                frame.Close()
                app.Yield()

    def test_preview_cross_selection_and_responsive_layout(self):
        import wx
        from variant_manager_plugin.wayri_variants import service as S
        from variant_manager_plugin.wayri_variants.gui import VariantFrame, state_text
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'project_fusion_plugin/tests'))
        from test_sections_native import make_fixture
        app = wx.GetApp() or wx.App(False)
        self.assertIn('MPN=Demo-22k', state_text({'fields': {'Value': '22k', 'MPN': 'Demo-22k'}}))
        empty = VariantFrame()
        self.assertTrue(empty.GetIcons().GetIcon(wx.Size(64, 64)).IsOk())
        empty.Close()
        app.Yield()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'source'
            make_fixture(home)
            for path in home.glob('*.kicad_sch'):
                path.write_text(path.read_text().replace('20250114', '20260306'))
            project = home / 'board.kicad_pro'
            inv = S.inventory(project)
            key = next(o['key'] for o in inv['objects'] if o['kind'] == 'symbol')
            create = S.preview(project, [{'op': 'create', 'name': 'Production'}])
            S.apply(create, editors_closed=True)
            from variant_manager_plugin.wayri_variants.gui import board_geometry
            frame = VariantFrame()
            frame.project.SetValue('C:/Projects/VariantDemo/board.kicad_pro')
            frame.inventory = S.inventory(project)
            frame.geometry, note = board_geometry(project)
            frame.geometry_note.SetLabel(note)
            frame.plan = S.preview(project, [{'op': 'edit', 'variant': 'Production', 'keys': [key],
                                             'fields': {'Value': '22k'}, 'flags': {'dnp': True}}])
            frame.populate_names()
            frame.refresh_rows()
            frame.review.SetValue('Preview: Production changes R1 from 10k to 22k and marks it DNP.\nDrawing geometry, routing and connectivity stay unchanged. Save and close KiCad before Apply.')
            frame.apply_button.Enable()
            frame.Show()
            try:
                for size in ((1360, 900), (1000, 800)):
                    frame.SetSize(size)
                    frame.Layout()
                    for _ in range(5):
                        app.Yield()
                    self.assertGreater(frame.canvas.GetSize().height, 150)
                    self.assertGreater(frame.table.GetSize().height, 140)
                    self.assertFalse(frame.canvas.GetScreenRect().Intersects(frame.table.GetScreenRect()))
                    self.assertGreater(frame.table.GetItemCount(), 0)
                    frame.select_keys([key])
                    self.assertIn(key, frame.canvas.selected)
                    self.assertIn('22k', frame.table.GetItemText(1, 2))
                frame.SetSize((1360, 900))
                frame.Layout()
                for _ in range(5):
                    app.Yield()
                output = os.environ.get('VARIANT_SCREENSHOT')
                if output:
                    bitmap = wx.Bitmap(*frame.GetSize())
                    memory = wx.MemoryDC(bitmap)
                    # Capture only this test window, never another foreground app.
                    import ctypes
                    self.assertTrue(ctypes.windll.user32.PrintWindow(frame.GetHandle(), memory.GetHDC(), 2))
                    memory.SelectObject(wx.NullBitmap)
                    bitmap.SaveFile(output, wx.BITMAP_TYPE_PNG)
                frame.mode.SetSelection(1)
                frame.refresh_rows()
                self.assertEqual(frame.table.GetItemCount(), len(frame.plan.rows))
                self.assertEqual(frame.table.GetItemText(0, 3), 'Production')
                frame.project.SetValue('C:/Projects/Other/board.kicad_pro')
                self.assertIsNone(frame.plan)
                self.assertIsNone(frame.inventory)
                self.assertFalse(frame.apply_button.IsEnabled())
            finally:
                frame.Close()
                app.Yield()


if __name__ == '__main__':
    unittest.main()
