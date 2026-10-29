"""Independent circuit limits and extraction rejection for board RLC eyes."""
import json
import unittest

import numpy as np

from signal_integrity_advisor_plugin.board_eye import simulate_board_eye, transfer
from signal_integrity_advisor_plugin.eye_model import simulate_eye
from signal_integrity_advisor_plugin.eye_view import eye_section
from signal_integrity_advisor_plugin.measurement import PathMeasurement


def section(r=0., l=50e-9, c=20e-12, kind='track'):
    return dict(kind=kind, resistance_ohm=r, inductance_h=l, capacitance_f=c)


def path(r=0.):
    return PathMeasurement('DATA', 'U1.1', 'J1.1', status='ok', length_mm=150,
        segments=[dict(kind='track', status='ok', reference_layer='In1.Cu',
            item_uuid='track-1', layer='F.Cu', resistance_ohm=r,
            inductance_nh=50, capacitance_pf=20, length_mm=150)],
        track_count=1, impedance_valid=True, impedance_ohm=50, propagation_delay_ns=1)


class TransferTests(unittest.TestCase):
    def test_dc_divider_and_open_receiver(self):
        for load in (None, 25, 100):
            answer = transfer([section(r=3), section(r=7)], [0], 20, load)[0]
            expected = 1 if load is None else load/(20+10+load)
            self.assertAlmostEqual(answer.real, expected, places=13)
            self.assertAlmostEqual(answer.imag, 0, places=13)
        np.testing.assert_array_equal(transfer([section()], [0, 1e9], 50, 0), [0, 0])

    def test_matched_lossless_exact_delay(self):
        f = np.linspace(0, 10e9, 1001)
        expected = .5*np.exp(-2j*np.pi*f*1e-9)
        np.testing.assert_allclose(transfer([section()], f, 50, 50), expected, atol=1e-13)

    def test_uniform_section_subdivision_invariant(self):
        f = np.linspace(0, 5e9, 701)
        whole = transfer([section(r=5)], f, 25, 100, 2)
        pieces = [section(r=.5, l=5e-9, c=2e-12)]*10
        np.testing.assert_allclose(transfer(pieces, f, 25, 100, 2), whole, rtol=1e-12, atol=1e-12)

    def test_receiver_rc_without_route_matches_analytic_pole(self):
        f = np.linspace(0, 5e9, 701)
        np.testing.assert_allclose(transfer([], f, 50, None, 20),
                                   1/(1+2j*np.pi*f*50*20e-12), atol=1e-13)

    def test_nonuniform_order_changes_asymmetrically_terminated_channel(self):
        a = section(r=1, l=80e-9, c=10e-12)
        b = section(r=1, l=20e-9, c=40e-12)
        f = np.linspace(1e6, 2e9, 201)
        self.assertGreater(np.max(abs(transfer([a,b], f, 20, 100)-transfer([b,a], f, 20, 100))), .1)

    def test_passive_matched_power_cannot_exceed_available_source_power(self):
        f = np.linspace(0, 10e9, 1001)
        channel = [section(r=2, l=80e-9, c=10e-12), section(r=4, l=20e-9, c=40e-12)]
        self.assertLessEqual(float(np.max(abs(2*transfer(channel, f, 50, 50)))), 1+1e-12)

    def test_via_pi_matches_independent_nodal_equations(self):
        # Solve node voltages from KCL, independent of the two-port cascade.
        f = np.linspace(1e6, 4e9, 101)
        r, l, c, rs, rl = .1, 1e-9, .4e-12, 25, 75
        expected = []
        for freq in f:
            y = 1/(r+2j*np.pi*freq*l)
            shunt = 2j*np.pi*freq*c/2
            matrix = np.array([[1/rs+y+shunt, -y], [-y, 1/rl+y+shunt]])
            expected.append(np.linalg.solve(matrix, [1/rs, 0])[1])
        np.testing.assert_allclose(transfer([section(r,l,c,'via')], f, rs, rl), expected, atol=1e-13)


class BoardEyeTests(unittest.TestCase):
    def simulate(self, route=None, **changes):
        inputs = dict(topology={'complete':True}, source_ohm=50,
                      load_ohm=50, rise_ns=.1, bitrate_mbps=1000)
        inputs.update(changes)
        return simulate_board_eye(route or path(), **inputs)

    def test_lossless_matches_existing_exact_bounce_model(self):
        result = self.simulate()
        reference = simulate_eye(z0_ohm=50, delay_ns=1, source_ohm=50,
                                 load_ohm=50, rise_ns=.1, bitrate_mbps=1000)
        np.testing.assert_allclose(result['traces_v'], reference['traces_v'], atol=.005)
        step = result['step_response']
        expected = .5*np.clip((np.array(step['time_ns'])-1)/.125, 0, 1)
        np.testing.assert_allclose(step['voltage_v'], expected, atol=.005)
        self.assertEqual(result['status'], 'SIMULATED')
        self.assertLessEqual(result['numerics']['waveform_refinement_error_v'], .005)
        self.assertLessEqual(result['numerics']['step_history_error_v'], .001)
        self.assertLessEqual(result['numerics']['step_settling_error_v'], .001)
        json.dumps(result, allow_nan=False)

    def test_copper_loss_and_receiver_capacitance_change_eye(self):
        baseline = self.simulate()
        lossy = self.simulate(path(40))
        capacitive = self.simulate(load_pf=10)
        self.assertLess(lossy['center_opening_v'], baseline['center_opening_v'])
        self.assertGreater(np.max(abs(np.array(capacitive['traces_v'])-baseline['traces_v'])), .05)
        self.assertAlmostEqual(lossy['numerics']['dc_receiver_v'], 50/140)
        html = eye_section(lossy)
        self.assertIn('Board RLC eye', html)
        self.assertIn('waveform refinement error v', html)

    def test_step_export_includes_long_reflection_settling(self):
        result = self.simulate(path(1), source_ohm=1, load_ohm=None)
        step = result['step_response']
        self.assertGreater(step['time_ns'][-1], 5)
        self.assertAlmostEqual(step['voltage_v'][-1], 1, delta=.001)

    def test_missing_topology_or_section_parasitics_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, 'topology'):
            self.simulate(topology=None)
        for changes in ({'capacitance_pf':None}, {'inductance_nh':float('nan')},
                        {'resistance_ohm':-1}, {'status':'partial'}, {'reference_layer':''}):
            route = path(); route.segments[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.simulate(route)

    def test_nonuniform_section_z0_does_not_block_valid_cascade(self):
        route = path()
        route.impedance_valid = False
        route.blockers = [dict(code='NONUNIFORM_IMPEDANCE')]
        self.assertEqual(self.simulate(route)['status'], 'SIMULATED')
        route.blockers += [dict(code='REFERENCE_PLANE_MISSING')]
        with self.assertRaisesRegex(ValueError, 'REFERENCE_PLANE_MISSING'):
            self.simulate(route)

    def test_via_partial_inductance_is_not_silently_used(self):
        route = path(); route.via_count = route.layer_changes = 1
        route.status = 'partial'
        route.segments.append(dict(kind='via', resistance_ohm=.01,
                                   inductance_nh=900, capacitance_pf=None))
        with self.assertRaisesRegex(ValueError, 'Via return-loop'):
            self.simulate(route)
        result = self.simulate(route, via_l_nh=.5, via_c_pf=.2)
        self.assertAlmostEqual(result['channel_sections'][1]['inductance_h'], .5e-9)
        route.layer_changes = 2
        with self.assertRaisesRegex(ValueError, 'pad-only'):
            self.simulate(route, via_l_nh=.5, via_c_pf=.2)

    def test_undamped_channel_and_unresolvable_bandwidth_fail_honestly(self):
        with self.assertRaises(ValueError):
            self.simulate(source_ohm=0, load_ohm=None)
        with self.assertRaisesRegex(ValueError, 'converge'):
            self.simulate(rise_ns=.001)


if __name__ == '__main__':
    unittest.main()
