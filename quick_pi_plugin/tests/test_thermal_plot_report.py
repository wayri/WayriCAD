"""QuickTherm saved-board visualization and exported evidence."""
from pathlib import Path
import tempfile
import unittest

from matplotlib.figure import Figure

from quick_pi_plugin.thermal_plot import draw_thermal_view
from quick_pi_plugin.report import write_diagnostic_report


VIEW={'outline':[{'outer_mm':[[0,0],[10,0],[10,8],[0,8]],'holes_mm':[]}],
      'bbox_mm':[0,0,10,8],
      'components':[{'id':'u1','reference':'U1','position_mm':[2,2],
                     'top_side':True,'side':'top','in_scope':True,'solved':True,
                     'junction_c':35,'issues':[]},
                    {'id':'u2','reference':'U2','position_mm':[8,6],
                     'top_side':False,'side':'bottom','in_scope':True,'solved':False,
                     'junction_c':None,'issues':['missing power']}],
      'field':{'status':'unavailable','reason':'Need three anchors',
               'meaning':'Interpolated junction estimates; not board surface temperature.'},
      'analytics':{'temperature_c':{'min':35,'max':35,'mean':35,'median':35},
                   'hottest_reference':'U1'}}


class ThermalPlotReportTests(unittest.TestCase):
    def test_modes_draw_with_excluded_component(self):
        for mode in ('Top-side map','Bottom-side map','Top-side contour','Bottom-side contour',
                     'Top board model','Bottom board model','3D overview','Temperature chart'):
            figure=Figure(figsize=(5,3))
            draw_thermal_view(figure,VIEW,mode,'u2')
            self.assertTrue(figure.axes)

    def test_report_contains_map_analytics_and_excluded_row(self):
        bundle={'board_thermal_view':VIEW,
                'quick_therm':{'model':'Lumped steady-state screen','environment':'air','ambient_c':25,
                    'board_c':None,'coverage':{'scoped':2,'solved':1,
                        'excluded':[{'reference':'U2','issues':['missing power']}]},
                    'components':[{'reference':'U1','power_w':1.,'resistance_k_per_w':10.,
                        'junction_c':35.,'rise_above_ambient_k':10.,'heat_path':'air'}],
                    'assumptions':['Illustrative test values']}}
        with tempfile.TemporaryDirectory() as directory:
            result=write_diagnostic_report(Path(directory)/'therm.html',bundle)
            html=Path(result['html']).read_text(encoding='utf-8')
            self.assertIn('Top-side map',html)
            self.assertIn('Top-side contour',html)
            self.assertIn('Bottom-side map',html)
            self.assertIn('3D overview',html)
            self.assertIn('Temperature analytics',html)
            self.assertIn('missing power',html)
            self.assertIn('data:image/png;base64,',html)

    def test_report_includes_optional_board_heat_balance_and_3d(self):
        field={'x_centers_mm':[2,8],'y_centers_mm':[2,6],
               'values_c':[[30.,31.],[32.,33.]],'sampled_min_c':30.,'sampled_max_c':33.}
        thermal={'model':'lumped screen','environment':'air','ambient_c':25.,'board_c':None,
                 'coverage':{'scoped':1,'solved':1,'excluded':[]},
                 'components':[{'reference':'U1','power_w':1.,'resistance_k_per_w':10.,
                                'junction_c':35.,'rise_above_ambient_k':10.,'heat_path':'air'}],
                 'assumptions':[]}
        network={'model':'thin-sheet board screen','status':'converged','board_field':field,
                 'settings':{'board_k_w_mk':.3},'assumptions':['No CFD'],
                 'components':[{'reference':'U1','side':'top','heat_path':'board',
                                'source_heat_path':'air','board_site_c':32.,'sink_c':None,'junction_c':None}],
                 'heat_balance':{'input_w':1.,'board_convection_w':.6,'board_radiation_w':.4,
                                 'sink_convection_w':0.,'sink_radiation_w':0.,'residual_w':0.}}
        with tempfile.TemporaryDirectory() as directory:
            path=write_diagnostic_report(Path(directory)/'model.html',
                 {'quick_therm':thermal,'board_thermal_view':VIEW,'thermal_network':network})['html']
            html=Path(path).read_text(encoding='utf-8')
            self.assertIn('Top board model',html)
            self.assertIn('Bottom board model',html)
            self.assertIn('3D overview',html)
            self.assertIn('Board-network component sites',html)
            self.assertIn('residual',html)

    def test_layered_field_mount_flux_and_report(self):
        field={'id':0,'name':'F.Cu','z_mm':0.0175,
               'x_centers_mm':[2,8],'y_centers_mm':[2,6],
               'values_c':[[20.,21.],[22.,23.]],'sampled_min_c':20.,'sampled_max_c':23.}
        other={**field,'id':31,'name':'B.Cu','z_mm':1.5825,
               'values_c':[[15.,16.],[17.,18.]],'sampled_min_c':15.,'sampled_max_c':18.}
        network={'model':'layer-resolved screen','status':'converged','layers':[field,other],
                 'settings':{'dielectric_k_w_mk':.3},'assumptions':['test'],
                 'components':[{'reference':'U1','side':'top','board_site_c':22.,'junction_c':None}],
                 'mounts':[{'id':'hole-1','temperature_c':10.,'heat_flux_w':.7}],
                 'heat_balance':{'input_w':1.,'convection_w':.2,'radiation_w':.1,
                                 'mount_flux_w':.7,'residual_w':0.}}
        for mode in ('Layer model: F.Cu','Layer model: B.Cu','3D overview'):
            figure=Figure(figsize=(5,3))
            draw_thermal_view(figure,VIEW,mode,network=network)
            self.assertTrue(figure.axes)
        thermal={'model':'lumped screen','environment':'air','ambient_c':20.,'board_c':None,
                 'coverage':{'scoped':1,'solved':1,'excluded':[]},
                 'components':[{'reference':'U1','power_w':1.,'resistance_k_per_w':10.,
                                'junction_c':30.,'rise_above_ambient_k':10.,'heat_path':'air'}],
                 'assumptions':[]}
        with tempfile.TemporaryDirectory() as directory:
            path=write_diagnostic_report(Path(directory)/'layered.html',
                {'quick_therm':thermal,'board_thermal_view':VIEW,'thermal_network':network})['html']
            html=Path(path).read_text(encoding='utf-8')
            self.assertIn('Layer model: F.Cu',html)
            self.assertIn('Fixed-temperature contacts',html)
            self.assertIn('hole-1',html)


if __name__=='__main__':unittest.main()
