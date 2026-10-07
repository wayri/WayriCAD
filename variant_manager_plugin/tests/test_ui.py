"""Opt-in native wx interaction, preview and layout checks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('VARIANT_NATIVE_UI') == '1', 'Opt-in KiCad wx native window')
class NativeUI(unittest.TestCase):
    def test_preview_cross_selection_and_responsive_layout(self):
        import wx
        from variant_manager_plugin.wayri_variants import service as S
        from variant_manager_plugin.wayri_variants.gui import VariantFrame
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'project_fusion_plugin/tests'))
        from test_sections_native import make_fixture
        app = wx.App(False)
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
