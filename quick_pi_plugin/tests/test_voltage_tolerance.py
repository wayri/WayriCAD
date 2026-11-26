'''Percentage supply limits, native maps and numerical evidence.'''

import unittest

from quick_pi_plugin.report import cell_values, draw_view, result_scale, tolerance_html
from quick_pi_plugin.service import sink_requests
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.voltage_tolerance import annotate, limits, refresh, voltage_text


class VoltageToleranceTests(unittest.TestCase):
    def test_limits_apply_to_each_load_and_exact_bounds_can_narrow_them(self):
        request=dict(source_voltage=3.3,voltage_tolerance_pct=5,
                     sinks=[dict(terminal='J1.1',current_A=.2),
                            dict(terminal='J2.1',power_W=.3,min_voltage_V=3.2,max_voltage_V=3.4)])
        first,second=sink_requests(request)
        self.assertAlmostEqual(first['min_voltage_V'],3.135)
        self.assertAlmostEqual(first['max_voltage_V'],3.465)
        self.assertEqual((second['min_voltage_V'],second['max_voltage_V']),(3.2,3.4))
        request['sinks'][1]['min_voltage_V']=3.6
        request['sinks'][1]['max_voltage_V']=3.7
        with self.assertRaisesRegex(ValueError,'do not overlap'):
            sink_requests(request)

    def test_invalid_nominal_and_percentage_fail_at_boundary(self):
        for nominal,pct in [(0,5),(-1,5),(3.3,-1),(3.3,101),(3.3,float('nan')),(3.3,True)]:
            with self.subTest(nominal=nominal,pct=pct),self.assertRaises(ValueError):
                limits(nominal,pct)
        self.assertEqual(limits(2,0),(2,2))

    def test_compliance_percent_and_width_rows_are_human_readable(self):
        result=dict(source_voltage_V=3.3,sinks=[dict(id='load',label='J1.1',voltage_V=3.134,
                     min_voltage_V=3.135,max_voltage_V=3.465,within_voltage_limits=False)],
                     trace_width_guidance=dict(notice='Analytical estimate',rows=[
                     dict(location_mm=[1,2],existing_width_mm=.2,recommended_width_mm=.3,width_change_mm=.1)]))
        annotate(result,dict(source_voltage=3.3,voltage_tolerance_pct=5))
        self.assertEqual(result['voltage_tolerance']['loads'][0]['state'],'Fail')
        html=tolerance_html(result)
        self.assertIn('±5%',html);self.assertIn('Trace width guidance',html)
        self.assertNotIn('3.135 V',html)
        self.assertIn('3.135 V',tolerance_html(result,True))
        result['sinks'][0].update(voltage_V=3.14,within_voltage_limits=True)
        refresh(result)
        self.assertEqual(result['voltage_tolerance']['loads'][0]['state'],'Near limit')

    def test_percentage_scale_matches_the_absolute_nodal_extrema(self):
        data=bundle()
        nominal=data['result']['source_voltage_V']
        for absolute, relative, factor in [('drop','drop_pct',.1),('voltage','voltage_pct',100.)]:
            for actual,expected in zip(result_scale(data,relative),result_scale(data,absolute)):
                self.assertAlmostEqual(actual,expected*factor/nominal)

    def test_percentage_tolerance_survives_batch_and_checks_the_delivered_voltage(self):
        from quick_pi_plugin.batch import initial_study, validate_study
        from quick_pi_plugin.power_loop import summarize_loop
        request=dict(net='3V3', source_terminal='A', sink_terminal='B', source_voltage=3.3,
                     sink_current=1, voltage_tolerance_pct=5, show_exact_voltages=False)
        case=validate_study(initial_study(request))['cases'][0]['electrical']
        self.assertEqual(case['voltage_tolerance_pct'],5)
        self.assertIs(case['show_exact_voltages'],False)
        evidence=dict(sink_current_A=1,energy_relative_error=0,current_balance_error_A=0,
                      voltage_drop_V=.1,total_power_W=.1,sink_voltage_V=3.2)
        loop=summarize_loop(case,evidence,evidence,dict(sink_terminal='GND'))
        self.assertAlmostEqual(loop['delivered_load_voltage_V'],3.1)
        self.assertFalse(loop['feasible'])

    def test_plot_and_probe_use_same_relative_field(self):
        import numpy as np
        from matplotlib.figure import Figure
        data=bundle()
        data['request']['voltage_tolerance_pct']=5
        result=data['result'];mesh=data['mesh']
        expected=cell_values(mesh,result,'drop')/(10*result['source_voltage_V'])
        np.testing.assert_allclose(cell_values(mesh,result,'drop_pct'),expected,atol=1e-12)
        axes=draw_view(Figure(),data,board_view=True)
        self.assertEqual(axes._wayricad_color_scale['unit'],'%')
        data['view_settings']={'show_exact_voltages':True}
        axes=draw_view(Figure(),data,board_view=True)
        self.assertEqual(axes._wayricad_color_scale['unit'],'mV')
        self.assertEqual(voltage_text(result,None,exact=False),'Unavailable')
