"""Reference checks for voltage-driven and swept DC series paths."""
import math
import unittest

from quick_pi_plugin.operating_point import current_sweep,load_current,path_drop
from quick_pi_plugin.service import _operating_result
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip


class OperatingPointTests(unittest.TestCase):
    def test_resistive_load_matches_voltage_divider(self):
        current=load_current(5.,2.,3.)
        self.assertAlmostEqual(current,1.,12)
        self.assertAlmostEqual(path_drop(current,2.),2.,12)

    def test_fixed_drop_reduces_voltage_driven_current(self):
        branches=[{'id':'D1','fixed_drop_v':1.}]
        self.assertAlmostEqual(load_current(5.,1.,3.,branches),1.,12)
        with self.assertRaisesRegex(ValueError,'cannot forward-bias'):
            load_current(.5,1.,3.,branches)

    def test_anchored_diode_root_satisfies_kvl(self):
        branches=[{'id':'D1','diode':{'vf_ref_v':.7,'reference_current_a':1.,
                                     'ideality':2.,'temperature_c':25.}}]
        current=load_current(4.,.1,3.,branches)
        self.assertGreater(current,1.)
        self.assertAlmostEqual(path_drop(current,.1,branches)+3*current,4.,12)
        rows=current_sweep(4.,.1,branches,[.5,1.,2.])
        self.assertEqual(len(rows),3)
        self.assertAlmostEqual(rows[1]['components'][0]['forward_drop_V'],.7,8)
        self.assertGreater(rows[2]['components'][0]['forward_drop_V'],rows[1]['components'][0]['forward_drop_V'])
        self.assertTrue(all(math.isfinite(row['sink_voltage_V']) for row in rows))

    def test_service_reuses_mesh_for_load_and_sweep(self):
        mesh,source,sink=strip()
        mesh['terminal_nodes']={'source':source,'sink':sink}
        output={'mesh':mesh,'geometry':{'terminals':[]},
                'result':solve(mesh,source,sink,sink_current=1.)}
        request={'action':'solve','source_terminal':'source','sink_terminal':'sink',
                 'source_voltage':5.,'load_resistance_ohm':10.}
        solved=_operating_result(output,request,request,True,False)
        result=solved['result']
        self.assertAlmostEqual(result['sink_voltage_V'],result['sink_current_A']*10.,10)
        self.assertEqual(result['operating_mode'],'voltage_driven_resistive_load')
        basis={'mesh':mesh,'geometry':{'terminals':[]},
               'result':solve(mesh,source,sink,sink_current=1.)}
        sweep_request={'action':'sweep','source_terminal':'source','sink_terminal':'sink',
                       'source_voltage':5.,'sweep':{'start_A':.1,'stop_A':2.,'points':5}}
        swept=_operating_result(basis,sweep_request,sweep_request,False,True)
        self.assertNotIn('result',swept)
        self.assertEqual(len(swept['sweep']['rows']),5)


if __name__=='__main__':unittest.main()
