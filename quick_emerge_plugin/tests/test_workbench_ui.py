"""Native UI workflows: units, lazy charts, original-sample probes and invalidation."""
import copy
from pathlib import Path
import sys
import unittest
try:
    if sys.platform!='win32':raise ImportError('Native Windows display test')
    import wx
    from quick_emerge_plugin.ui import QuickEMergeFrame
except ImportError:
    wx=None

@unittest.skipIf(wx is None,'Windows wx display unavailable')
class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=wx.App.Get() or wx.App(False)
    def setUp(self):
        self.frame=QuickEMergeFrame(Path(__file__).parent/'fixtures/region_coupon.kicad_pcb')
        self.frame.SetSize((1120,780));self.frame.Show();wx.Yield()
    def tearDown(self):self.frame.close(None);wx.Yield()
    def result(self):
        from quick_emerge_plugin.model import config_digest,source_identity
        f=self.frame;f.mode.SetSelection(1);f.invalidate();config=f.config()
        return {'schema':1,'backend':{'backend':'EMerge','version':'3.0.0b9'},'config':config,'config_sha256':config_digest(config),
                'source':source_identity(f.session.board),'model_scope':'parametric-template','port_count':2,'frequencies_hz':[1e9,2e9],
                's_parameters':{'S11':[[.1,0],[.2,0]],'S12':[[.8,0],[.7,0]],'S21':[[.8,0],[.7,0]],'S22':[[.1,0],[.2,0]]},
                'field':{'x_mm':[0,1,2],'y_mm':[0,2],'z_mm':1,'frequency_hz':1e9,'norm_e_v_m':[[1,2,3],[4,5,6]],'norm_h_a_m':[[2,3,4],[5,6,7]]},'assumptions':['Analytical test fixture; not a solver execution']}
    def test_visual_frequency_units_boolean_controls_and_focus(self):
        f=self.frame
        self.assertTrue(f.GetIcons().GetIconOfExactSize(wx.Size(64,64)).IsOk())
        f.navigate('3D'); self.assertEqual(list(f.view_choice.GetItems()), ['3D setup'])
        self.assertIsInstance(f.config()['advanced']['coupled_thermal'],bool)
        f.inputs['f_start_hz'].ChangeValue('4000000000')
        self.assertEqual(wx.TextCtrl.GetValue(f.inputs['f_start_hz']),'4')
        self.assertEqual(float(f.inputs['f_start_hz'].GetValue()),4e9)
        self.assertFalse(f.visual_splitter.IsSplit())
        f.toggle_inspector(show=True);f.focus_button.SetValue(True);f.focus_view()
        self.assertFalse(f.workspace_splitter.IsSplit())
        f.focus_button.SetValue(False);f.focus_view();self.assertTrue(f.visual_splitter.IsSplit())
    def test_primary_materials_and_progressive_study_settings(self):
        f=self.frame
        self.assertEqual([f.setup_book.GetPageText(i) for i in range(3)],['1  Geometry','2  Physics','3  Solve'])
        self.assertTrue(f.advanced_pane.IsCollapsed())
        f.setup_book.SetSelection(1);wx.Yield()
        self.assertTrue(f.advanced_inputs['loss_tangent'].IsShownOnScreen())
        self.assertTrue(f.advanced_inputs['conductor'].IsShownOnScreen())
        self.assertFalse(f.advanced_inputs['abc_order'].IsShownOnScreen())
        f.study.SetSelection(f.study_ids.index('waveguide'));f.update_model_sections();wx.Yield()
        self.assertTrue(f.advanced_inputs['waveguide_width_mm'].IsShownOnScreen())
        self.assertTrue(f.advanced_pane.IsCollapsed())
        f.SetSize((960,650));f.Layout();wx.Yield()
        self.assertGreater(f.workspace.GetClientSize().width,500)
        view=f.viewports['3D setup']
        canvas=view.window if hasattr(view,'window') else view.canvas
        self.assertGreater(canvas.GetClientSize().height,250)

    def test_toolbar_buttons_remain_content_sized_and_selector_is_readable(self):
        f=self.frame
        for width in (960,1600):
            f.SetSize((width,780));f.navigate('2D');f.Layout();wx.Yield()
            with self.subTest(window_width=width):
                self.assertLessEqual(f.focus_button.GetSize().width,
                    f.focus_button.GetBestSize().width+f.FromDIP(4))
                text_width=f.view_choice.GetTextExtent('PCB enclosure').width
                self.assertGreaterEqual(f.view_choice.GetClientSize().width,text_width+f.FromDIP(30))
        for name in ('PCB enclosure','3D setup'):
            f.select_view(name);f.Layout();wx.Yield()
            image=next(child for child in f.viewports[name].GetChildren()
                if isinstance(child,wx.Button) and child.GetLabel()=='Image…')
            with self.subTest(view=name):
                self.assertLessEqual(image.GetSize().width,image.GetBestSize().width+f.FromDIP(4))

    def test_lazy_charts_linked_probes_and_stale_setup(self):
        f=self.frame;r=self.result();original=copy.deepcopy(r);f.install_result(r);wx.Yield()
        self.assertFalse(f.viewports['S-parameters'].figure.axes)
        f.select_view('S-parameters');wx.Yield();self.assertEqual(len(f.viewports['S-parameters'].figure.axes),1)
        f.select_view('Field probes');wx.Yield()
        event=type('Point',(),{'inaxes':True,'xdata':1,'ydata':2})()
        f.probe('Field probes',event);f.pin_probe(None)
        self.assertEqual(f.pins[-1]['value_v_m'],5)
        self.assertEqual(f.viewports['3D fields'].selection['x_mm'],1)
        f.field_quantity.SetStringSelection('H magnitude');f.change_field_quantity();wx.Yield()
        self.assertEqual(f.inspection.unit,'A/m');self.assertEqual(f.inspection.probe(1,2)['value_a_m'],6)
        self.assertEqual(r,original)
        f.inputs['er'].SetValue('3.8');wx.Yield()
        self.assertIsNone(f.result);self.assertTrue(all(v.renderer is None for v in f.viewports.values()))
    def test_fit_holdout_warning_is_visible(self):
        from quick_emerge_plugin.model import config_digest
        from quick_emerge_plugin.network import from_result
        from quick_emerge_plugin.network_extensions import serialize_network
        f=self.frame; result=self.result(); f.install_result(result)
        f.network_signature=config_digest(f.config())
        output=dict(operation={'kind':'fit'},derived_network=serialize_network(from_result(result)),
                    fit=dict(absolute_tolerance_requested=1e-5,holdout_max_abs_error=.1))
        f._network_ready(output,None); wx.Yield()
        self.assertIn('Fit needs validation',f.GetStatusBar().GetStatusText())
        self.assertIs(f.result,result)

    def test_coupled_temperature_is_separate_from_em_quantities(self):
        f=self.frame;r=self.result();r['thermal']={'x_mm':[0,1,2],'y_mm':[0,2],'z_mm':0,'temperature_k':[[300,301,302],[303,304,305]],'time_s':0,'peak_k':305}
        f.install_result(r);self.assertEqual(f.inspection.unit,'V/m')
        f.field_quantity.SetStringSelection('Temperature');f.change_field_quantity();wx.Yield()
        row=f.inspection.probe(1,2);self.assertEqual(row['temperature_k'],304);self.assertNotIn('frequency_hz',row)
        f.probe('Field probes',type('Point',(),{'inaxes':True,'xdata':1,'ydata':2})());f.pin_probe(None)
        self.assertEqual(f.pins[-1]['unit'],'K')

if __name__=='__main__':unittest.main()
