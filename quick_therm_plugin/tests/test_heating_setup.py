"""Reviewed units and budgets for the spatial heating guide."""
import copy
import unittest
from quick_therm_plugin.heating_setup import time_seconds, heating_settings, heating_advice, watt_step_schedules, watt_step_rows


def settings(**updates):
    return dict(duration_s='10 s', timestep_s='100 ms', frame_interval_s='100 ms',
                initial_c='20', copper_volumetric_capacity_j_m3k='3450000',
                dielectric_volumetric_capacity_j_m3k='1800000', **updates)


class HeatingSetupTests(unittest.TestCase):
    def test_time_units_are_explicit_and_invalid_values_rejected(self):
        for raw, expected in [('2 min',120),('100 ms',.1),('1h',3600),('.5',.5),('1e-3 s',.001)]:
            self.assertEqual(time_seconds(raw), expected)
        for raw in ['0','-1','nan','inf','1 us','1.2.3','10 seconds',True]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):time_seconds(raw)

    def test_settings_require_reviewed_capacity_and_physical_initial_temperature(self):
        data=settings(); original=copy.deepcopy(data); normalized=heating_settings(data)
        self.assertEqual(data,original)
        self.assertEqual(normalized['duration_s'],10)
        self.assertEqual(normalized['timestep_s'],.1)
        for key, value in [('initial_c','-273.15'),('initial_c','10001'),
                           ('copper_volumetric_capacity_j_m3k','0'),
                           ('dielectric_volumetric_capacity_j_m3k','nan')]:
            data=settings();data[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):heating_settings(data)

    def test_frame_and_regular_step_limits_fail_before_worker(self):
        data=settings();data['frame_interval_s']='1 ms'
        with self.assertRaisesRegex(ValueError,'stored frames'):heating_settings(data)
        data=settings();data['timestep_s']='0.1 ms'
        with self.assertRaisesRegex(ValueError,'solver steps'):heating_settings(data)

    def test_advice_retains_event_cost_without_claiming_exact_mesh(self):
        data=heating_settings(settings());schedule={'U1':[[0,1],[.25,0],[4,1]]}
        advice=heating_advice(data,schedule)
        self.assertEqual(advice['regular_frames'],101)
        self.assertEqual(advice['schedule_events'],2)
        self.assertEqual(advice['frame_upper_bound'],103)
        self.assertEqual(advice['nodes_per_frame_budget'],5000000//103)
        self.assertIn('mesh',advice['note'])

    def test_actual_watts_convert_without_modifying_base_or_schedule(self):
        rows=[('U1','2','3','0'),('U2','0.5','',''),('U3','0','','')]
        powers={'U1':4.,'U2':.5,'U3':0.};original=copy.deepcopy((rows,powers))
        self.assertEqual(watt_step_schedules(rows,powers,10),
            {'U1':[[0.,.5],[3.,0.]],'U2':[[0.,1.]],'U3':[[0.,0.]]})
        self.assertEqual((rows,powers),original)
        for base, initial, switch, final in [(None,1,'',''),(0,1,'',''),(1,-1,'',''),
                                              (1,'nan','',''),(1,1,11,0),(1,1,'',0)]:
            with self.subTest(base=base),self.assertRaises(ValueError):
                watt_step_schedules([('U1',initial,switch,final)],{'U1':base},10)

    def test_schedule_readback_keeps_advanced_and_invalid_profiles_out_of_simple_editor(self):
        powers={'U1':2.}
        self.assertEqual(watt_step_rows(['U1'],powers,{'U1':[[0,.25],[1,0]]}),
                         [['U1','2.0','0.5','1','0.0']])
        for schedule in [[],{'U1':[]},{'U1':[[0,1],[1,0],[2,1]]},
                         {'U1':[[0,'bad']]},{'U1':[[0,float('nan')]]},
                         {'U1':[[2,1]]},{'U1':[[0,1],[0,0]]}]:
            original=copy.deepcopy(schedule)
            with self.subTest(schedule=schedule),self.assertRaises(ValueError):
                watt_step_rows(['U1'],powers,schedule)
            self.assertEqual(str(schedule),str(original))

    def test_watts_schedule_reaches_expected_adiabatic_energy(self):
        from quick_therm_plugin.thermal_spatial_transient import evolve
        from scipy.sparse import csr_matrix
        import numpy as np
        schedule=watt_step_schedules([('U1',2, .25,0)],{'U1':4.},1)
        answer=evolve(csr_matrix((1,1)),[2],{'U1':np.array([4.])},[0],[0],[0],20,[0],[0],{},
            dict(duration_s=1,timestep_s=.2,frame_interval_s=.1,
                 power_schedules=schedule,schedule_interpolation='step'))
        self.assertAlmostEqual(answer['final_temperatures_c'][0],20.25)
        self.assertAlmostEqual(sum(row['input_energy_j'] for row in answer['energy_balance']),.5)
