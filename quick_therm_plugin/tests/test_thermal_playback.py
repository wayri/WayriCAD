"""Computed-frame selection, fixed scales, and explicit native power steps."""
import unittest
from quick_therm_plugin.thermal_playback import frame_at_time, step_schedules, transient_temperature_limits
from quick_therm_plugin.thermal_review import transient_frame_network


class PlaybackTests(unittest.TestCase):
    def test_decimated_frames_retain_switch_events(self):
        from quick_therm_plugin.thermal_spatial_transient import evolve
        from scipy.sparse import csr_matrix
        import numpy as np
        result=evolve(csr_matrix((1,1)),[1],{'U1':np.array([1])},[0],[0],[0],20,[0],[0],{},
            {'duration_s':10,'timestep_s':1,'frame_stride':5,'schedule_interpolation':'step',
             'power_schedules':{'U1':[[0,0],[2.25,1],[2.5,0]]}})
        self.assertTrue({0,2.25,2.5,10}.issubset({frame['time_s'] for frame in result['frames']}))
        self.assertAlmostEqual(result['final_temperatures_c'][0],20.25)

    def test_actual_frame_times_are_held_without_invented_interpolation(self):
        frames=[{'time_s':0},{'time_s':.25},{'time_s':5}]
        self.assertEqual([frame_at_time(frames,t) for t in (-1,0,.1,.25,4.99,5,9)], [0,0,0,1,1,2,2])
        self.assertIsNone(frame_at_time([],1))

    def test_board_scale_excludes_separate_sink_and_keeps_zero(self):
        transient={'spatial_index':{'active_cells_per_layer':2,'layers':[{'id':0}]},
                   'frames':[{'temperatures_c':[0,20,400]}, {'temperatures_c':[10,50,500]}]}
        self.assertEqual(transient_temperature_limits(transient),(0,50))
        self.assertEqual(transient_temperature_limits({'frames':[{'temperatures_c':[20,20]}]}),(19.5,20.5))
        self.assertIsNone(transient_temperature_limits({}))

    def test_power_step_editor_requires_explicit_valid_values(self):
        self.assertEqual(step_schedules([('U1','1','2.5','0'),('U2','0','','')],10),
                         {'U1':[[0.,1.],[2.5,0.]],'U2':[[0.,0.]]})
        for values in [('nan','',''),('-1','',''),('1','0','2'),('1','11','2'),('1','2','-1'),('1','','2')]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                step_schedules([('U1',*values)],10)

    def test_frame_power_changes_at_step_and_bounds_are_current(self):
        network={'layers':[{}],'components':[], 'transient':{
            'schedule_interpolation':'step','power_schedules':{'U1':[[0,1],[2,0]]},
            'frames':[{'time_s':1,'temperatures_c':[30]},{'time_s':2,'temperatures_c':[31]}],
            'spatial_index':{'cells':[[0,0]],'active_cells_per_layer':1,'x_centers_mm':[0],'y_centers_mm':[0]},
            'components':[{'reference':'U1','nodes':[[0,1]],'power_w':2,'junction_resistance_k_per_w':5}]}}
        before=transient_frame_network(network,0);after=transient_frame_network(network,1)
        self.assertEqual(before['components'][0]['junction_c'],40)
        self.assertEqual(after['components'][0]['junction_c'],31)
        self.assertEqual(after['components'][0]['power_w'],0)
        self.assertEqual(after['layers'][0]['sampled_max_c'],31)
        self.assertEqual(network['layers'],[{}])
