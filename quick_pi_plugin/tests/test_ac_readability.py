"""AC presentation preserves SI evidence while making discrete results readable."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from quick_pi_plugin.ac_report import draw, engineering, summary, write_report
from quick_pi_plugin.tests.test_ac_workflow import result_bundle


class ACReadabilityTests(unittest.TestCase):
    def test_single_harmonic_is_discrete_and_uses_engineering_units(self):
        bundle=result_bundle();original=copy.deepcopy(bundle)
        figure=Figure(figsize=(11,6));FigureCanvasAgg(figure);draw(figure,bundle);figure.canvas.draw()
        geometry,impedance,losses=figure.axes
        self.assertEqual(impedance.get_xscale(),'linear')
        self.assertEqual(len(impedance.patches),2);self.assertEqual(len(losses.patches),1)
        self.assertEqual([p.get_height() for p in impedance.patches],[5.,20.])
        self.assertEqual(losses.patches[0].get_height(),5.)
        self.assertIn('mΩ',impedance.get_ylabel());self.assertIn('mW',losses.get_ylabel())
        self.assertIn('kHz',impedance.get_xlabel())
        self.assertEqual(list(impedance.get_xticks()),[100000.])
        self.assertEqual(bundle,original)

    def test_multiple_harmonics_keep_frequency_coordinates_for_selection(self):
        bundle=result_bundle();bundle['ac']['harmonics'].append(dict(bundle['ac']['harmonics'][0],frequency_hz=1e6))
        figure=Figure(figsize=(11,6));FigureCanvasAgg(figure);draw(figure,bundle);figure.canvas.draw()
        self.assertEqual(len(figure.axes),3)
        self.assertEqual(figure.axes[1].get_xscale(),'log')
        self.assertEqual(list(figure.axes[1].lines[0].get_xdata()),[100000.,1000000.])
        self.assertIn('MHz',figure.axes[1].get_xlabel())

    def test_uniform_field_has_no_artificial_spatial_colorbar(self):
        bundle=result_bundle();bundle['ac']['cells']=[{'conductor':'Supply','x_mm':0.,'y_mm':0.,'width_mm':.1,'height_mm':.07,'current_density_rms_a_mm2':30.,'loss_density_w_mm3':.001}]
        figure=Figure(figsize=(11,6));draw(figure,bundle)
        self.assertEqual(len(figure.axes[0].child_axes),0)
        self.assertTrue(any('Uniform RMS' in item.get_text() for item in figure.axes[0].texts))
        bundle['ac']['cells'].append(dict(bundle['ac']['cells'][0],x_mm=.1,current_density_rms_a_mm2=40.))
        draw(figure,bundle)
        self.assertEqual(len(figure.axes[0].child_axes),1)

    def test_missing_harmonic_values_are_unknown_not_zero_bars(self):
        bundle=result_bundle()
        for key in ('resistance_ohm','reactance_ohm','loss_w'):bundle['ac']['harmonics'][0][key]=None
        figure=Figure(figsize=(11,6));draw(figure,bundle)
        for axis in figure.axes[1:]:
            self.assertEqual(len(axis.patches),0)
            self.assertTrue(any('No supplied harmonic result' in item.get_text() for item in axis.texts))

    def test_selected_chart_views_keep_axis_identity_and_short_canvas_clear(self):
        bundle=result_bundle()
        bundle['ac']['cells']=[{'conductor':'Supply','x_mm':x,'y_mm':0.,'width_mm':.1,'height_mm':.07,'current_density_rms_a_mm2':value,'loss_density_w_mm3':.001} for x,value in [(0.,30.),(.1,40.)]]
        for view,index in [('geometry',0),('impedance',1),('losses',2)]:
            with self.subTest(view=view):
                figure=Figure(figsize=(9,3.1),dpi=100);FigureCanvasAgg(figure)
                draw(figure,bundle,view=view);figure.canvas.draw()
                self.assertEqual(len(figure.axes),3)
                self.assertEqual([a.get_visible() for a in figure.axes],[i==index for i in range(3)])
                if view=='geometry':
                    axis=figure.axes[0];bar=axis.child_axes[0]
                    renderer=figure.canvas.get_renderer()
                    self.assertGreater(axis.xaxis.label.get_window_extent(renderer).y0,bar.bbox.y1+2)
                    self.assertGreaterEqual(bar.xaxis.label.get_window_extent(renderer).y0,0)
                else:
                    self.assertTrue(all(not a.get_visible() for a in figure.axes[0].child_axes))
                    self.assertEqual(len(figure.axes[0].collections),0)
        with self.assertRaises(ValueError):draw(Figure(),bundle,view='unknown')

    def test_summary_is_readable_without_json_and_unknowns_not_zero(self):
        bundle=result_bundle();text=summary(bundle)
        self.assertIn('128 mW',text);self.assertIn('AC ripple copper heating: 5 mW',text)
        self.assertNotIn('{',text)
        self.assertEqual(engineering(None,'V'),'Unknown')
        self.assertEqual(engineering(0.,'V'),'0 V')
        self.assertEqual(engineering(100000.,'Hz'),'100 kHz')

    def test_wide_short_native_canvas_does_not_clip_colourbar_caption(self):
        bundle=result_bundle()
        bundle['ac']['cells']=[{'conductor':'Supply','x_mm':x,'y_mm':0.,'width_mm':.1,'height_mm':.07,'current_density_rms_a_mm2':value,'loss_density_w_mm3':.001} for x,value in [(0.,30.),(.1,40.)]]
        figure=Figure(figsize=(13.4,2.73),dpi=100);FigureCanvasAgg(figure)
        draw(figure,bundle,view='geometry');figure.canvas.draw()
        bar=figure.axes[0].child_axes[0]
        self.assertGreaterEqual(bar.xaxis.label.get_window_extent(figure.canvas.get_renderer()).y0,4)
        from matplotlib.text import Annotation
        title=figure.axes[0]._left_title.get_window_extent(figure.canvas.get_renderer())
        for text in figure.axes[0].texts:
            if isinstance(text,Annotation):self.assertFalse(title.overlaps(text.get_window_extent(figure.canvas.get_renderer())))

    def test_html_and_evidence_keep_status_and_exact_si_values(self):
        bundle=result_bundle();bundle['ac']['status']='UNCONVERGED';original=copy.deepcopy(bundle)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'result.html';write_report(path,bundle)
            html=path.read_text(encoding='utf-8')
            self.assertIn('UNCONVERGED',html);self.assertIn('Provisional result',html)
            self.assertIn('one supplied harmonic',html)
            self.assertIn('Resistance (mΩ)',html);self.assertIn('Heating (mW)',html)
            self.assertIn('report-raw-evidence',html)
            self.assertEqual(json.loads(path.with_suffix('.json').read_text(encoding='utf-8')),original)
            self.assertEqual(bundle,original)


if __name__=='__main__':unittest.main()
