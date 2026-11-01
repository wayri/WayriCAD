"""Native minimal workspace, original-data toggles and atomic plot output."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    if sys.platform != 'win32': raise ImportError('Native Windows display test')
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
    from quick_emerge_plugin.workspace_actions import build_export_menu, export_plot
except ImportError:
    wx = None


@unittest.skipIf(wx is None, 'Windows wx display unavailable')
class MinimalWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = wx.App.Get() or wx.App(False)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.board = self.root/'example.kicad_pcb'
        shutil.copyfile(Path(__file__).parent/'fixtures/region_coupon.kicad_pcb', self.board)
        self.frame = QuickEMergeFrame(self.board)
        self.frame.SetSize((1280, 800)); self.frame.Show(); wx.Yield()

    def tearDown(self):
        self.frame.close(None); wx.Yield(); self.temporary.cleanup()

    def result(self):
        from quick_emerge_plugin.model import config_digest, source_identity
        f = self.frame; f.mode.SetSelection(1); f.invalidate(); config = f.config()
        return dict(schema=1, backend={'backend':'EMerge','version':'3.0.0b9'}, config=config,
            config_sha256=config_digest(config), source=source_identity(self.board), model_scope='parametric-template',
            port_count=2, frequencies_hz=[config['f_start_hz'], config['f_stop_hz']],
            s_parameters={'S11':[[.1,0],[.2,0]],'S12':[[.8,0],[.7,0]],'S21':[[.8,0],[.7,0]],'S22':[[.1,0],[.2,0]]},
            field=dict(x_mm=[0,1,2],y_mm=[0,2],z_mm=1,frequency_hz=config['f_start_hz'],
                       norm_e_v_m=[[1,2,3],[4,5,6]],norm_h_a_m=[[2,3,4],[5,6,7]]),
            assumptions=['Analytical UI fixture; not a FEM execution'])

    def test_plain_views_fill_canvas_and_do_not_show_extra_toolbars(self):
        f = self.frame
        self.assertEqual(list(f.navigation), ['2D', '3D'])
        for size in ((980,650),(1280,800),(1600,900)):
            f.SetSize(size); f.Layout(); wx.Yield()
            for name in ('PCB enclosure','3D setup'):
                f.select_view(name); wx.Yield()
                viewport = f.viewports[name]
                canvas = getattr(viewport, 'window', getattr(viewport, 'canvas', None))
                self.assertFalse(f.view_selectors.IsShown())
                self.assertFalse(viewport.controls_visible)
                self.assertGreaterEqual(canvas.GetSize().width, f.GetClientSize().width*.95)
                self.assertGreaterEqual(canvas.GetSize().height, f.GetClientSize().height*.75)
                self.assertIsNotNone(viewport.renderer)
        self.assertFalse(f.results_button.IsEnabled())

    def test_result_toggle_preserves_dimension_model_and_geometry(self):
        f = self.frame; result = self.result(); original = copy.deepcopy(result)
        f.install_result(result); config = f.config()
        for dimension, geometry, field in (('2D','PCB enclosure','Field probes'),('3D','3D setup','3D fields')):
            f.select_view(geometry); wx.Yield()
            f.results_button.SetValue(True); f.toggle_result_view(); wx.Yield()
            self.assertEqual(f.current_group, dimension)
            self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()), field)
            f.results_button.SetValue(False); f.toggle_result_view(); wx.Yield()
            self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()), geometry)
        self.assertEqual(f.config(), config); self.assertIs(f.result, result); self.assertEqual(result, original)
        self.assertTrue(f.results_button.IsEnabled())

    def test_export_menu_disables_missing_results_and_fields(self):
        f = self.frame
        menu = build_export_menu(f)
        try:
            items = [item for item in menu.GetMenuItems() if not item.IsSeparator()]
            self.assertEqual([item.IsEnabled() for item in items], [True,True,False,False,False])
        finally:
            menu.Destroy()
        result = self.result(); result.pop('field'); f.install_result(result)
        f.results_button.SetValue(True)
        menu = build_export_menu(f)
        try:
            items = [item for item in menu.GetMenuItems() if not item.IsSeparator()]
            self.assertEqual([item.IsEnabled() for item in items], [False,False,True,True,True])
        finally:
            menu.Destroy()

    def test_png_exports_have_real_geometry_extension_and_atomic_replacement(self):
        for dimension in ('2D','3D'):
            path = export_plot(self.frame, dimension, self.root/('view-'+dimension))
            self.assertEqual(path.suffix, '.png')
            self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            self.assertGreater(path.stat().st_size, 10000)
        self.assertFalse(list(self.root.glob('.view-*.png')))

    def test_stale_config_or_source_preserves_existing_destination(self):
        f = self.frame; path = self.root/'protected.png'; path.write_bytes(b'original')
        f.inputs['er'].ChangeValue(3.8)
        with self.assertRaisesRegex(ValueError,'setup changed'):
            export_plot(f, '2D', path)
        self.assertEqual(path.read_bytes(), b'original')
        f.preview(None)
        self.board.write_bytes(self.board.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'Board or setup changed'):
            export_plot(f, '2D', path)
        self.assertEqual(path.read_bytes(), b'original')

    def test_partial_render_failure_does_not_replace_destination_or_leave_staging(self):
        f = self.frame; path = self.root/'protected.png'; path.write_bytes(b'original')
        viewport = f.viewports['PCB enclosure']
        def fail(temporary, **kwargs):
            Path(temporary).write_bytes(b'partial'); raise OSError('Renderer failed')
        with patch.object(viewport.figure, 'savefig', side_effect=fail):
            with self.assertRaisesRegex(OSError,'Renderer failed'): export_plot(f, '2D', path)
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('.protected-*.png')))

    def test_plot_chooser_starts_in_board_project_and_cancelling_keeps_view(self):
        f = self.frame; selected = f.tabs.GetSelection()
        with patch('quick_emerge_plugin.workspace_actions.wx.FileDialog') as dialog:
            dialog.return_value.__enter__.return_value.ShowModal.return_value = wx.ID_CANCEL
            self.assertIsNone(export_plot(f, '2D'))
            self.assertEqual(dialog.call_args.kwargs['defaultDir'], str(self.board.parent))
        self.assertEqual(f.tabs.GetSelection(), selected)

    def test_new_inputs_clear_result_toggle_and_return_to_geometry(self):
        f = self.frame; f.install_result(self.result()); f.select_view('Field probes'); wx.Yield()
        f.inputs['er'].SetValue(3.8); wx.Yield()
        self.assertIsNone(f.result); self.assertFalse(f.results_button.GetValue())
        self.assertFalse(f.results_button.IsEnabled())
        self.assertEqual(f.current_group, '2D')
        self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()), 'PCB enclosure')

    def test_geometry_and_field_toggle_preserves_3d_camera(self):
        f = self.frame; f.install_result(self.result()); f.select_view('3D setup'); wx.Yield()
        geometry = f.viewports['3D setup']; geometry.set_camera(preset='Right'); geometry.zoom(.8)
        if hasattr(geometry, 'scene'):
            before = geometry.scene.GetActiveCamera().GetPosition()
        else:
            before = (geometry.axes().elev, geometry.axes().azim, *geometry.axes().get_xlim())
        f.results_button.SetValue(True); f.toggle_result_view(); wx.Yield()
        field = f.viewports['3D fields']
        after = field.scene.GetActiveCamera().GetPosition() if hasattr(field, 'scene') else (
            field.axes().elev, field.axes().azim, *field.axes().get_xlim())
        for a,b in zip(before,after): self.assertAlmostEqual(a,b)
        f.results_button.SetValue(False); f.toggle_result_view(); wx.Yield()
        after = geometry.scene.GetActiveCamera().GetPosition() if hasattr(geometry, 'scene') else (
            geometry.axes().elev, geometry.axes().azim, *geometry.axes().get_xlim())
        for a,b in zip(before,after): self.assertAlmostEqual(a,b)

    def test_exporting_other_dimension_preserves_result_mode_and_original_values(self):
        f = self.frame; result = self.result(); original = copy.deepcopy(result); f.install_result(result)
        f.select_view('3D fields'); wx.Yield()
        path = export_plot(f, '2D', self.root/'field.png')
        self.assertEqual(f.current_group, '2D'); self.assertTrue(f.results_button.GetValue())
        self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()), 'Field probes')
        self.assertGreater(path.stat().st_size, 10000)
        self.assertIs(f.result, result); self.assertEqual(result, original)
        f.results_button.SetValue(False); f.toggle_result_view(); wx.Yield()
        export_plot(f, '3D', self.root/'geometry.png')
        self.assertEqual(f.current_group, '3D'); self.assertFalse(f.results_button.GetValue())
        self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()), '3D setup')

    def test_native_more_export_and_files_menu_events_dispatch_without_context_manager(self):
        f = self.frame
        from quick_emerge_plugin.workspace_actions import build_more_menu
        for build, label, callback in ((build_more_menu,'Display settings…','show_view_options'),
                                       (build_export_menu,'Save 2D plot (PNG)…','export_plot')):
            with patch.object(f, callback) as handler:
                menu = build(f)
                try:
                    item = next(item for item in menu.GetMenuItems() if item.GetItemLabelText() == label)
                    menu.ProcessEvent(wx.CommandEvent(wx.EVT_MENU.typeId, item.GetId()))
                    handler.assert_called_once()
                finally: menu.Destroy()
        with patch.object(f.files_button,'PopupMenu') as popup:
            f.show_files(); popup.assert_called_once()

    def test_preview_replaces_stale_footer_and_keeps_results_unavailable(self):
        f = self.frame; f.inputs['er'].SetValue(3.8); wx.Yield()
        self.assertIn('Setup changed', f.probe_label.GetLabel())
        f.preview(None); wx.Yield()
        self.assertIn('Geometry preview', f.probe_label.GetLabel())
        self.assertNotIn('Setup changed', f.probe_label.GetLabel())
        self.assertFalse(f.results_button.IsEnabled())

    def test_source_change_during_render_preserves_previous_destination(self):
        f = self.frame; path = self.root/'protected.png'; path.write_bytes(b'original')
        viewport = f.viewports['PCB enclosure']; save = viewport.figure.savefig
        def changed_source(temporary, **kwargs):
            save(temporary, **kwargs); self.board.write_bytes(self.board.read_bytes()+b'\n')
        with patch.object(viewport.figure, 'savefig', side_effect=changed_source):
            with self.assertRaisesRegex(ValueError,'Board or setup changed'): export_plot(f, '2D', path)
        self.assertEqual(path.read_bytes(), b'original')
        self.assertFalse(list(self.root.glob('.protected-*.png')))

    def test_added_extension_never_bypasses_existing_file_confirmation(self):
        from quick_emerge_plugin.workspace_actions import output_path
        path = self.root/'existing.png'; path.write_bytes(b'original')
        with patch('quick_emerge_plugin.workspace_actions.wx.MessageBox', return_value=wx.NO) as confirm:
            self.assertIsNone(output_path(self.root/'existing', '.png', self.frame, confirm_added_extension=True))
            confirm.assert_called_once()
        self.assertEqual(path.read_bytes(), b'original')
        with self.assertRaisesRegex(ValueError,'Choose a .png'):
            output_path(self.root/'wrong.jpg', '.png', self.frame)

    def test_report_choosers_start_in_project_folder_and_cancel_without_generation(self):
        f = self.frame; f.install_result(self.result())
        for kind in ('html','pdf'):
            with patch('quick_emerge_plugin.ui.wx.FileDialog') as dialog:
                dialog.return_value.__enter__.return_value.ShowModal.return_value = wx.ID_CANCEL
                f.generate_report(kind)
                self.assertEqual(dialog.call_args.kwargs['defaultDir'], str(self.board.parent))
                self.assertEqual(Path(dialog.call_args.kwargs['defaultFile']).suffix, '.'+kind)
        self.assertFalse(getattr(f, 'report_busy', False))


if __name__ == '__main__': unittest.main()
