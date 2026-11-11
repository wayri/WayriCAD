"""Opt-in EMerge execution checks, not array convergence or measured agreement."""
import json
import os
import unittest

from quick_emerge_plugin.fem_array import fem_aesa_config
from quick_emerge_plugin.model import validate_config


@unittest.skipUnless(os.environ.get('QUICK_EMERGE_REAL_TESTS')=='1','requires explicit real EMerge runtime')
class FEMArrayRealTests(unittest.TestCase):
    def test_small_steered_fem_array_retains_coupling_and_excitation_evidence(self):
        from quick_emerge_plugin.backend import solve
        from quick_emerge_plugin.qualification import smoke_configs, check_result
        base=dict(smoke_configs()[1][1],points=2,substrate_x_mm=60,substrate_y_mm=40,max_tets=30000)
        config=validate_config(dict(base,advanced=dict(study='array',array_count_x=2,array_count_y=1,
                   array_pitch_x_mm=25,array_pitch_y_mm=25,array_excitation_mode='scan_angle',
                   scan_theta_deg=30,array_taper='binomial',array_power_w=2)))
        result=solve(config,qualifying=True)
        check_result(result,config)
        self.assertEqual(result['port_count'],2)
        self.assertNotIn('array_factor',result)
        self.assertEqual(result['backend']['backend'],'EMerge')
        self.assertGreater(result['discretization']['tetrahedra'],0)
        self.assertLess(result['array']['superposition_relative_error'],1e-10)
        self.assertEqual(len(result['array']['power_accounting']),2)
        self.assertAlmostEqual(result['array']['power_accounting'][0]['incident_power_w'],2)
        self.assertTrue(all(value is False for value in result['array']['s_parameter_corrections'].values()))
        self.assertIn('boresight_polarization',result['radiation'])
        json.dumps(result,allow_nan=False)

    def test_four_by_four_geometry_has_sixteen_distinct_physical_ports(self):
        import numpy as np
        import emerge as em
        from quick_emerge_plugin.advanced_studies import build_array_geometry
        model,air,ports,widths,thickness=build_array_geometry(em,np,fem_aesa_config(4,4,30))
        self.assertEqual(len(ports),16)
        self.assertEqual(len(widths),16)
        self.assertEqual(len(set(tuple(p) for p in model._quick_array_centers)),16)
        self.assertEqual(len(model._quick_conductors),17)
        self.assertFalse(model.settings.mw_cap_sp_single)
        self.assertFalse(model.settings.mw_cap_sp_col)


if __name__=='__main__': unittest.main()
