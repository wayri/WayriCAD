"""Native original-sample polar/3D radiation workflow and export custody."""
import copy
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

try:
    if sys.platform!='win32': raise ImportError('Native Windows display test')
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
    from quick_emerge_plugin.workspace_actions import build_more_menu,export_plot,result_views
except ImportError:
    wx=None

from quick_emerge_plugin.tests.test_radiation_pattern import pattern


@unittest.skipIf(wx is None,'Windows wx display unavailable')
class RadiationWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=wx.App.Get() or wx.App(False)

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.board=self.root/'board.kicad_pcb'
        shutil.copyfile(Path(__file__).parent/'fixtures/region_coupon.kicad_pcb',self.board)
        self.original=self.board.read_bytes()
        self.frame=QuickEMergeFrame(self.board);self.frame.SetSize((1280,800));self.frame.Show();wx.Yield()

    def tearDown(self):
        self.assertEqual(self.board.read_bytes(),self.original)
        self.frame.close(None);wx.Yield();self.temporary.cleanup()

    def result(self):
        from quick_emerge_plugin.model import config_digest,source_identity
        f=self.frame;f.mode.SetSelection(1);f.inputs['points'].ChangeValue(3);f.invalidate();config=f.config()
        frequencies=[config['f_start_hz'],(config['f_start_hz']+config['f_stop_hz'])/2,config['f_stop_hz']]
        radiation=pattern(lambda theta,phi:abs(math.sin(theta))*(1+.3*math.cos(phi)))
        radiation['frequency_hz']=frequencies[1]
        return dict(schema=1,backend={'backend':'EMerge','version':'3.0.0b9'},config=config,
            config_sha256=config_digest(config),source=source_identity(self.board),model_scope='parametric-template',
            port_count=2,frequencies_hz=frequencies,
            s_parameters={'S11':[[.1,0]]*3,'S12':[[.8,0]]*3,'S21':[[.8,0]]*3,'S22':[[.1,0]]*3},
            field=dict(x_mm=[0,1,2],y_mm=[0,2],z_mm=1,frequency_hz=frequencies[1],norm_e_v_m=[[1,2,3],[4,5,6]]),
            radiation=radiation,assumptions=['Analytical UI fixture; not a FEM execution'])

    def test_polarization_is_visible_only_with_saved_complex_components(self):
        result = self.result()
        result['radiation']['boresight_polarization'] = {'ex_ri': [1, 0], 'ey_ri': [0, 1]}
        self.frame.install_result(result)
        self.assertIn('3D polarization', result_views(result, '3D'))
        self.frame.select_view('3D polarization'); wx.Yield()
        self.assertEqual(self.frame.tabs.GetPageText(self.frame.tabs.GetSelection()), '3D polarization')
        view = self.frame.viewports['3D polarization']
        if hasattr(view, 'scene'):
            self.assertGreaterEqual(view.scene.GetActors().GetNumberOfItems(), 2)
            self.assertIn('not a spatial field', view.scope_caption)
        else:
            self.assertEqual(view.axes().name, '3d')

    def test_phase_vectors_use_saved_components_and_stop_on_close(self):
        result = self.result()
        result['field']['e_real_v_m'] = np.ones((3, 2, 3)).tolist()
        result['field']['e_imag_v_m'] = np.zeros((3, 2, 3)).tolist()
        frame = self.frame
        frame.install_result(result)
        frame.field_view.SetSelection(2)
        frame.refresh_field_views()
        frame.select_view('3D fields'); wx.Yield()
        initial = frame.viewports['3D fields'].arguments['field']['display_vectors']
        view=frame.viewports['3D fields']
        self.assertIn('instantaneous_vector', view.picking[0])
        if hasattr(view, 'data_actor'):
            self.assertIsNotNone(view.data_actor)
            self.assertIsNotNone(view.data_actor.GetMapper().GetInput().GetPointData().GetArray('original_vector_index'))
        frame.field_phase.SetValue(180); frame.refresh_field_views(); wx.Yield()
        other = frame.viewports['3D fields'].arguments['field']['display_vectors']
        np.testing.assert_allclose(other['vectors'], -initial['vectors'])
        np.testing.assert_array_equal(other['positions'], initial['positions'])
        frame.animate_phase.SetValue(True); frame.toggle_field_animation()
        self.assertTrue(frame.phase_timer.IsRunning())
        frame.animate_phase.SetValue(False); frame.toggle_field_animation()
        self.assertFalse(frame.phase_timer.IsRunning())

    def test_array_factor_exposes_native_3d_lobes(self):
        from quick_emerge_plugin.research_studies import solve_rectangular_array_factor
        from quick_emerge_plugin.research_antennas import example_config
        from quick_emerge_plugin.model import source_identity
        config = example_config('verho-2023-aesa-4x4')
        config['advanced']['scan_theta_deg'] = 30
        self.frame._apply_setup_config(config, self.board)
        result = solve_rectangular_array_factor(np, config, {})
        result['source'] = source_identity(self.board)
        self.frame.install_result(result)
        self.frame.select_view('3D radiation'); wx.Yield()
        self.assertEqual(self.frame.tabs.GetPageText(self.frame.tabs.GetSelection()), '3D radiation')
        self.assertIn('3D radiation', result_views(result, '3D'))
        self.assertGreater(len(self.frame.viewports['3D radiation'].picking), 10000)

    def test_array_overview_shows_interactive_3d_and_scaled_2d_together(self):
        from quick_emerge_plugin.research_studies import solve_rectangular_array_factor
        from quick_emerge_plugin.research_antennas import example_config
        from quick_emerge_plugin.model import source_identity
        config=example_config('verho-2023-aesa-4x4')
        config['advanced']['scan_theta_deg']=30
        f=self.frame;f._apply_setup_config(config,self.board)
        result=solve_rectangular_array_factor(np,config,{'backend':'Ideal array factor','version':1})
        result['source']=source_identity(self.board)
        original=copy.deepcopy(result)
        f.install_result(result);f.show_radiation_overview();wx.Yield()
        overview=f.radiation_overview
        self.assertEqual(f.workspace_stack.GetSelection(),3)
        self.assertTrue(overview.scene_view.IsShownOnScreen())
        self.assertTrue(overview.cut_view.IsShownOnScreen())
        self.assertEqual(overview.cut_view.axes().name,'polar')
        self.assertEqual(overview.cut_view.axes().get_ylim(),(0,1.05))
        self.assertIn('Ideal array factor',overview.caption.GetLabel())
        self.assertIn('not dBi',overview.caption.GetLabel())
        self.assertGreater(len(overview.scene_view.picking),10000)
        overview.cut_choice.SetStringSelection('YZ cut');overview.change_cut();wx.Yield()
        self.assertEqual(overview.cut_view.options['radiation_cut'],'YZ cut')
        self.assertEqual(result,original)
        row=overview.cut_view.picking[4]
        from types import SimpleNamespace
        overview._probe('Radiation pattern',SimpleNamespace(inaxes=True),row,True)
        self.assertEqual(overview.scene_view.selection['theta_index'],row['theta_index'])
        self.assertIn('relative |E|',overview.readout.GetLabel())
        f.inputs['er'].SetValue('4.0');wx.Yield()
        self.assertIsNone(overview.result)
        self.assertIsNone(overview.scene_view.renderer)
        self.assertIsNone(overview.cut_view.renderer)
        self.assertFalse(f.radiation_overview_button.IsEnabled())

    def test_overview_resize_stacks_views_on_narrow_window(self):
        f=self.frame;f.install_result(self.result());f.show_radiation_overview();wx.Yield()
        f.SetSize((980,700));wx.Yield()
        overview=f.radiation_overview
        if overview.GetClientSize().width < overview.FromDIP(850):
            self.assertEqual(overview.splitter.GetSplitMode(),wx.SPLIT_HORIZONTAL)
        self.assertIsNotNone(overview.cut_view.renderer)

    def test_both_views_and_dimension_switch_preserve_radiation_kind(self):
        f=self.frame;result=self.result();before=copy.deepcopy(result);f.install_result(result)
        f.select_view('Radiation pattern');wx.Yield()
        self.assertTrue(f.radiation_cut.IsShownOnScreen());self.assertEqual(f.viewports['Radiation pattern'].axes().name,'polar')
        self.assertEqual(list(f.radiation_cut.GetItems()),['XZ cut','YZ cut','XY azimuth'])
        f.navigate('3D');wx.Yield();self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()),'3D radiation')
        f.navigate('2D');wx.Yield();self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()),'Radiation pattern')
        self.assertIn('not gain',f.probe_label.GetLabel());self.assertIn('sampled φ',f.probe_label.GetLabel())
        self.assertEqual(result,before)

    def test_radiation_camera_is_not_replaced_by_mm_geometry_on_toggle(self):
        f=self.frame;f.install_result(self.result());f.select_view('3D radiation');wx.Yield()
        radiation=f.viewports['3D radiation'];geometry=f.viewports['3D setup']
        if hasattr(radiation,'scene'):
            camera=radiation.scene.GetActiveCamera();before=(camera.GetPosition(),camera.GetFocalPoint())
            geometry.scene.GetActiveCamera().SetPosition(74,35,50);geometry.scene.GetActiveCamera().SetFocalPoint(74,35,0)
        else:
            before=radiation._bounds();geometry.axes().set(xlim=(60,90),ylim=(30,40),zlim=(-2,2))
        f.results_button.SetValue(False);f.toggle_result_view();wx.Yield()
        f.results_button.SetValue(True);f.toggle_result_view();wx.Yield()
        self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()),'3D radiation')
        after=(camera.GetPosition(),camera.GetFocalPoint()) if hasattr(radiation,'scene') else radiation._bounds()
        for expected,actual in zip(before,after):
            if expected is None:self.assertIsNone(actual)
            else:np.testing.assert_allclose(actual,expected)

    def test_click_and_pin_use_original_angular_sample_in_both_views(self):
        from matplotlib.backend_bases import MouseEvent
        f=self.frame;result=self.result();before=copy.deepcopy(result);f.install_result(result);f.select_view('Radiation pattern');wx.Yield()
        view=f.viewports['Radiation pattern'];view.canvas.draw()
        row=next(row for row in view.picking if abs(row['theta_deg']-90)<1e-8 and abs(row['phi_deg'])<1e-8)
        x,y=view.axes().transData.transform((row['angle_rad'],row['relative_e']))
        for name in ('button_press_event','button_release_event'):
            view.canvas.callbacks.process(name,MouseEvent(name,view.canvas,x,y,button=1))
        self.assertEqual(f.current_probe['theta_index'],row['theta_index']);self.assertEqual(f.current_probe['phi_index'],row['phi_index'])
        f.pin_probe(None);self.assertEqual(f.pins[-1]['relative_e'],1.)
        self.assertEqual(f.viewports['3D radiation'].selection['display_xyz'],row['display_xyz'])
        f.radiation_cut.SetStringSelection('YZ cut');f.change_radiation_cut();wx.Yield()
        self.assertFalse(any(item.get_gid()=='inspection-marker' for item in view.axes().collections))
        self.assertEqual(result,before)

    def test_radial_zoom_and_fit_do_not_pan_or_truncate_polar_angles(self):
        from matplotlib.backend_bases import MouseEvent
        f=self.frame;f.install_result(self.result());f.select_view('Radiation pattern');wx.Yield()
        view=f.viewports['Radiation pattern'];view.canvas.draw();axes=view.axes();angles=axes.get_xlim()
        view.zoom(.5);self.assertEqual(axes.get_xlim(),angles);self.assertEqual(axes.get_ylim()[0],0)
        self.assertLess(axes.get_ylim()[1],1.)
        view.set_mode('Pan');self.assertEqual(view.interaction,'Probe')
        view.canvas.draw();x,y=axes.transData.transform((.5,.25));before=view._bounds()
        for name,dx in (('button_press_event',0),('motion_notify_event',20),('button_release_event',20)):
            view.canvas.callbacks.process(name,MouseEvent(name,view.canvas,x+dx,y,button=2))
        self.assertEqual(view._bounds(),before)
        view.fit();self.assertEqual(axes.get_ylim(),(0,1.05));self.assertEqual(axes.get_xlim(),angles)

    def test_missing_or_invalid_patterns_disable_both_views_with_reason(self):
        f=self.frame;result=self.result();result.pop('radiation');f.install_result(result)
        self.assertNotIn('Radiation pattern',result_views(result,'2D'))
        menu=build_more_menu(f)
        try:
            items=[item for item in menu.GetMenuItems() if 'radiation pattern' in item.GetItemLabelText()]
            self.assertEqual(len(items),2);self.assertTrue(all(not item.IsEnabled() for item in items))
        finally:menu.Destroy()
        previous=f.tabs.GetSelection();f.select_view('Radiation pattern')
        self.assertEqual(f.tabs.GetSelection(),previous);self.assertIn('not recorded',f.GetStatusBar().GetStatusText())
        result=self.result();result['radiation']['norm_e'][0][0]=-1;f.install_result(result)
        f.select_view('3D radiation');self.assertIn('negative',f.GetStatusBar().GetStatusText())

    def test_partial_unknown_patterns_keep_gaps_and_export_both_dimensions(self):
        f=self.frame;result=self.result();result['radiation']['norm_e'][2][8]=None
        result['radiation']['norm_e'][0][0]=None
        before=copy.deepcopy(result);f.install_result(result);f.select_view('Radiation pattern');wx.Yield()
        view=f.viewports['Radiation pattern'];view.canvas.draw()
        self.assertTrue(np.isnan(view.axes().lines[0].get_ydata()).any())
        self.assertFalse(any(row['theta_index']==2 and row['phi_index']==8 for row in view.picking))
        for dimension in ('2D','3D'):
            path=export_plot(f,dimension,self.root/('radiation-'+dimension+'.png'))
            self.assertEqual(path.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(f.tabs.GetPageText(f.tabs.GetSelection()),'3D radiation')
        self.assertEqual(result,before)

    def test_changing_cut_survives_display_refresh_and_field_markers_are_not_projected(self):
        f=self.frame;f.install_result(self.result());f.select_view('Radiation pattern');wx.Yield()
        f.radiation_cut.SetStringSelection('YZ cut');f.change_radiation_cut();f.refresh_views();wx.Yield()
        view=f.viewports['Radiation pattern'];view.canvas.draw()
        self.assertIn('YZ cut',view.axes().get_title())
        view.set_selection(dict(kind='field',x_mm=1,y_mm=1,z_mm=1))
        self.assertFalse(any(item.get_gid()=='inspection-marker' for item in view.axes().collections))


if __name__=='__main__':unittest.main()
