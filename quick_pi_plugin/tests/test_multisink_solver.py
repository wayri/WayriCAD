"""Multisink current/energy balance and explicit source-capacity admission."""
import json
import unittest

from quick_pi_plugin.solver import solve, SolverError
from quick_pi_plugin.service import sink_requests
from quick_pi_plugin.tests.test_solver import strip, combine


class MultisinkSolverTests(unittest.TestCase):
    def parallel(self):
        a, sa, ta = strip()
        b, sb, tb = strip(length=20, width=2, z=1)
        mesh, offset = combine(a, b)
        return mesh, sa + [i + offset for i in sb], [ta, [i + offset for i in tb]]

    def specs(self, electrodes, currents=(1, 2), **limits):
        return [dict(nodes=nodes, id=str(i), label='Load ' + str(i), current_A=current, **limits)
                for i, (nodes, current) in enumerate(zip(electrodes, currents))]

    def test_independent_loads_have_separate_voltages_and_exact_total_loss(self):
        mesh, source, electrodes = self.parallel()
        result = solve(mesh, source, source_voltage=3.3, sinks=self.specs(electrodes), source_current_limit=4)
        resistance = 1.724e-8 * .01 / (.001 * .000035)
        self.assertAlmostEqual(result['source_current_A'], 3, 10)
        for current, row in zip((1, 2), result['sinks']):
            self.assertAlmostEqual(row['voltage_V'], 3.3-current*resistance, 12)
            self.assertAlmostEqual(row['voltage_drop_V'], current*resistance, 12)
        self.assertAlmostEqual(result['total_power_W'], 5*resistance, 12)
        self.assertLess(result['energy_relative_error'], 1e-10)
        self.assertLess(result['current_balance_error_A'], 1e-10)
        self.assertEqual(result['feasibility']['status'], 'FEASIBLE')
        self.assertEqual(result['feasibility']['source_current_headroom_A'], 1)
        self.assertEqual(result['drop_over_current_basis'], 'worst_sink_drop_over_total_demand')
        json.dumps(result, allow_nan=False)

    def test_shared_trunk_carries_sum_and_ideal_branch_currents_are_recovered(self):
        trunk, source, junction = strip()
        branch, bs, bt = strip(z=1)
        mesh, n = combine(trunk, branch)
        second, cs, ct = strip(z=2)
        mesh, k = combine(mesh, second)
        sinks = [ [i+n for i in bt], [i+k for i in ct] ]
        mesh['lumped_branches'] = [
            dict(id='A', top_nodes=junction, bottom_nodes=[i+n for i in bs], resistance_ohm=0, inductance_h=1e-6),
            dict(id='B', top_nodes=junction, bottom_nodes=[i+k for i in cs], resistance_ohm=0, inductance_h=1e-6)]
        result = solve(mesh, source, sinks=self.specs(sinks))
        resistance = 1.724e-8 * .01 / (.001 * .000035)
        self.assertAlmostEqual(result['total_power_W'], (3**2+1**2+2**2)*resistance, 12)
        for i, row in enumerate(result['sinks'], 1):
            self.assertAlmostEqual(row['voltage_drop_V'], (3+i)*resistance, 12)
        for i, row in enumerate(result['components'], 1):
            self.assertAlmostEqual(row['current_A'], i, 10)
            self.assertAlmostEqual(row['magnetic_energy_J'], .5e-6*i*i, 12)
        self.assertLess(result['energy_relative_error'], 1e-10)

    def test_source_limit_at_demand_is_feasible_and_overload_never_scales_loads(self):
        mesh, source, electrodes = self.parallel()
        specs = self.specs(electrodes)
        baseline = solve(mesh, source, sinks=specs)
        exact = solve(mesh, source, sinks=specs, source_current_limit=3)
        limited = solve(mesh, source, sinks=specs, source_current_limit=2.5)
        self.assertTrue(exact['feasibility']['feasible'])
        self.assertFalse(limited['feasibility']['operating_point_valid'])
        self.assertTrue(limited['feasibility']['source_current_limit_exceeded'])
        self.assertEqual(limited['feasibility']['source_current_headroom_A'], -.5)
        self.assertEqual(limited['potential_V'], baseline['potential_V'])
        self.assertEqual([s['current_A'] for s in limited['sinks']], [1, 2])
        self.assertIn('diagnostic', limited['feasibility']['notice'])
        off = solve(mesh, source, sinks=specs, source_current_limit=0)
        self.assertFalse(off['feasibility']['feasible'])
        fractional = solve(mesh, source, sinks=self.specs(electrodes, currents=(.1, .2)), source_current_limit=.3)
        self.assertTrue(fractional['feasibility']['feasible'])
        self.assertGreaterEqual(fractional['feasibility']['source_current_headroom_A'], 0)

    def test_each_voltage_window_is_checked_including_negative_voltage(self):
        mesh, source, electrodes = self.parallel()
        specs = self.specs(electrodes)
        specs[0]['min_voltage_V'] = .999
        specs[1]['max_voltage_V'] = .9
        result = solve(mesh, source, sinks=specs)
        self.assertFalse(result['sinks'][0]['within_voltage_limits'])
        self.assertFalse(result['sinks'][1]['within_voltage_limits'])
        self.assertFalse(result['feasibility']['feasible'])
        self.assertEqual(len(result['feasibility']['violations']), 2)
        negative = solve(mesh, source, source_voltage=.001, sinks=self.specs(electrodes))
        self.assertTrue(negative['negative_sink_voltage'])
        self.assertFalse(negative['feasibility']['feasible'])

    def test_legacy_solution_and_singleton_multisink_solution_match(self):
        mesh, source, sink = strip()
        legacy = solve(mesh, source, sink, sink_current=2)
        explicit = solve(mesh, source, sinks=[dict(nodes=sink, current_A=2)])
        for key in ('potential_V','cell_J_A_mm2','total_power_W','voltage_drop_V','source_current_A'):
            self.assertEqual(legacy[key], explicit[key])

    def test_exact_voltage_boundary_accepts_only_arithmetic_rounding(self):
        resistance = 1.724e-8 * .01 / (.001 * .000035)
        for nx, current in [(10, 2), (30, 1)]:
            mesh, source, sink = strip(nx=nx)
            voltage = 3.3-current*resistance
            result = solve(mesh, source, source_voltage=3.3,
                           sinks=[dict(nodes=sink, current_A=current, min_voltage_V=voltage, max_voltage_V=voltage)])
            self.assertTrue(result['feasibility']['feasible'])
            rejected = solve(mesh, source, source_voltage=3.3,
                             sinks=[dict(nodes=sink, current_A=current, min_voltage_V=voltage+1e-8)])
            self.assertFalse(rejected['feasibility']['feasible'])
        extreme = solve(mesh, source, sinks=[dict(nodes=sink, current_A=1000, max_voltage_V=1e20)])
        self.assertLess(extreme['sink_voltage_V'], 0)
        self.assertFalse(extreme['feasibility']['feasible'])
        self.assertLess(extreme['sinks'][0]['voltage_limit_tolerances_V']['minimum'], 1e-9)

    def test_order_does_not_change_physical_results(self):
        mesh, source, electrodes = self.parallel()
        specs = self.specs(electrodes)
        a = solve(mesh, source, sinks=specs)
        b = solve(mesh, source, sinks=list(reversed(specs)))
        self.assertEqual(a['potential_V'], b['potential_V'])
        self.assertEqual(a['total_power_W'], b['total_power_W'])

    def test_missing_connectivity_and_overlapping_loads_are_rejected(self):
        a, source, sink = strip()
        b, bs, bt = strip(z=1)
        mesh, n = combine(a, b)
        with self.assertRaisesRegex(SolverError, 'disconnected'):
            solve(mesh, source, sinks=self.specs([sink, [i+n for i in bt]]))
        for electrodes in ([sink, sink], [source, sink]):
            with self.assertRaisesRegex(SolverError, 'overlap'):
                solve(mesh, source, sinks=self.specs(electrodes))

    def test_nonfinite_negative_and_ambiguous_inputs_are_rejected(self):
        mesh, source, sink = strip()
        for limit in (float('nan'), float('inf'), -1, True):
            with self.subTest(limit=limit), self.assertRaises(SolverError):
                solve(mesh, source, sink, source_current_limit=limit)
        for spec in (dict(nodes=sink, current_A=0), dict(nodes=sink, current_A=True),
                     dict(nodes=sink, current_A=1, min_voltage_V=-1),
                     dict(nodes=sink, current_A=1, min_voltage_V=2, max_voltage_V=1)):
            with self.subTest(spec=spec), self.assertRaises(SolverError):
                solve(mesh, source, sinks=[spec])
        with self.assertRaises(SolverError): solve(mesh, source, sinks=[])
        with self.assertRaises(SolverError): solve(mesh, source, sink, sinks=[dict(nodes=sink, current_A=1)])
        with self.assertRaisesRegex(SolverError, 'Repeated'):
            solve(mesh, source, sinks=[dict(nodes=sink, current_A=1, id='x')]*2)


class MultisinkRequestTests(unittest.TestCase):
    def test_legacy_and_canonical_normalization(self):
        legacy = sink_requests(dict(sink_terminal='U1.1', sink_current=2, sink_min_voltage=3, sink_max_voltage=4))
        canonical = sink_requests(dict(sinks=[dict(terminal='U1.1', current_A=2, min_voltage_V=3, max_voltage_V=4)]))
        self.assertEqual(legacy, canonical)

    def test_invalid_loads_are_rejected_before_meshing(self):
        invalid = [dict(sinks=[]), dict(sinks='U1.1'), dict(sinks=[{}]),
                   dict(sinks=[dict(terminal='U1.1', current_A=1)]*2),
                   dict(sinks=[dict(terminal='U1.1', current_A=1)], sink_terminal='U1.1'),
                   dict(sinks=[dict(terminal='U1.1', current_A=1)], series=[{}]),
                   dict(sink_terminal='U1.1', source_current_limit=float('nan')),
                   dict(sink_terminal='U1.1', sink_current=True),
                   dict(sink_terminal='U1.1', sink_min_voltage=4, sink_max_voltage=3)]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError): sink_requests(request)


if __name__ == '__main__': unittest.main()
