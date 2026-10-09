"""Spatial copper law acceptance, with analytical parallel/series references."""
import copy
import unittest
from quick_pi_plugin.solver import solve, SolverError
from quick_pi_plugin.tests.test_solver import strip, combine


class SpatialTemperatureTests(unittest.TestCase):
    def test_uniform_array_preserves_scalar_and_energy(self):
        mesh, source, sink = strip()
        scalar = solve(mesh, source, sink, options={'temperature_c': 80})
        spatial = solve(mesh, source, sink, options={
            'triangle_temperature_c': [80]*len(mesh['triangles']),
            'material_temperature_range_c': [-20, 150]})
        self.assertAlmostEqual(scalar['total_power_W'], spatial['total_power_W'], 13)
        self.assertLess(spatial['energy_relative_error'], 1e-12)

    def test_parallel_layers_use_local_resistivity(self):
        a, sa, ta = strip()
        b, sb, tb = strip(z=1)
        mesh, n = combine(a, b)
        temperatures = [20]*len(a['triangles'])+[100]*len(b['triangles'])
        result = solve(mesh, sa+[i+n for i in sb], ta+[i+n for i in tb], options={
            'triangle_temperature_c': temperatures, 'material_temperature_range_c': [0, 150]})
        resistance = 1.724e-8*.01/(.001*.000035)
        hot = resistance*(1+.00393*80)
        self.assertAlmostEqual(result['drop_over_current_ohm'], 1/(1/resistance+1/hot), 12)
        self.assertLess(result['energy_relative_error'], 1e-12)

    def test_via_segment_owns_temperature(self):
        a, sa, ta = strip()
        b, sb, tb = strip(z=1.6)
        mesh, n = combine(a,b)
        mesh['vias'] = [dict(id='v',top_nodes=ta,bottom_nodes=[i+n for i in sb], length_mm=1.6,drill_mm=.3,plating_mm=.025)]
        cold = solve(mesh,sa,[i+n for i in tb])
        hot = solve(mesh,sa,[i+n for i in tb],options={'via_temperature_c':[100], 'material_temperature_range_c':[0,150]})
        self.assertAlmostEqual(hot['vias'][0]['resistance_ohm']/cold['vias'][0]['resistance_ohm'],1+.00393*80,12)
        self.assertAlmostEqual(hot['planar_power_W'],cold['planar_power_W'],12)
        self.assertLess(hot['energy_relative_error'],1e-12)

    def test_invalid_material_ownership_and_ranges(self):
        mesh, source, sink = strip()
        cases = [dict(triangle_temperature_c=[20]),
                 dict(triangle_temperature_c=[float('nan')]*len(mesh['triangles'])),
                 dict(triangle_temperature_c=[200]*len(mesh['triangles'])),
                 dict(via_temperature_c=[20])]
        for options in cases:
            options['material_temperature_range_c'] = [0,150]
            with self.subTest(options=options), self.assertRaises(SolverError):
                solve(mesh,source,sink,options=options)
        with self.assertRaisesRegex(SolverError,'require material'):
            solve(mesh,source,sink,options={'triangle_temperature_c':[20]*len(mesh['triangles'])})
