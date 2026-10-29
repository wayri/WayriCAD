"""Shared ground electrodes retain each load and add its current exactly once."""
import unittest
from quick_pi_plugin.solver import solve, SolverError
from quick_pi_plugin.terminals import resolve_units
from quick_pi_plugin.tests.test_solver import strip
from quick_pi_plugin.tests.test_shared_return import study
from quick_pi_plugin.batch import validate_study


class SharedContactsTests(unittest.TestCase):
    def setUp(self):
        self.mesh, self.source, self.end = strip()

    def test_two_loads_on_same_electrode_equal_combined_demand(self):
        shared = solve(self.mesh, self.source, source_voltage=0,
            sinks=[{'id':'A','nodes':self.end,'current_A':1},
                   {'id':'B','nodes':self.end,'current_A':2}], shared_return_contacts=True)
        combined = solve(self.mesh, self.source, self.end, source_voltage=0, sink_current=3)
        self.assertEqual([s['id'] for s in shared['sinks']], ['A','B'])
        self.assertAlmostEqual(shared['total_power_W'], combined['total_power_W'], 12)
        self.assertAlmostEqual(shared['source_current_A'], 3, 10)
        self.assertLess(shared['current_balance_error_A'], 1e-10)

    def test_reference_contact_demand_has_zero_drop_and_correct_total_current(self):
        result = solve(self.mesh, self.source, source_voltage=0,
            sinks=[{'id':'local','nodes':self.source,'current_A':4},
                   {'id':'remote','nodes':self.end,'current_A':2}], shared_return_contacts=True)
        reference = solve(self.mesh, self.source, self.end, source_voltage=0, sink_current=2)
        self.assertAlmostEqual(result['source_current_A'], 6, 10)
        self.assertEqual(result['sinks'][0]['voltage_drop_V'], 0)
        self.assertAlmostEqual(result['total_power_W'], reference['total_power_W'], 12)
        self.assertLess(result['current_balance_error_A'], 1e-10)

    def test_all_currents_at_reference_are_zero_loss_not_a_failed_solve(self):
        result = solve(self.mesh, self.source, source_voltage=0,
            sinks=[{'nodes':self.source,'current_A':7}], shared_return_contacts=True)
        self.assertEqual(result['total_power_W'], 0)
        self.assertEqual(result['source_current_A'], 7)
        self.assertEqual(result['energy_relative_error'], 0)

    def test_collapsed_mesh_has_no_unknown_potentials(self):
        result = solve(self.mesh, list(range(len(self.mesh['points_mm']))), source_voltage=0,
            sinks=[{'nodes':self.end,'current_A':7}], shared_return_contacts=True)
        self.assertEqual(result['total_power_W'], 0)
        self.assertEqual(result['source_current_A'], 7)

    def test_normal_supply_still_rejects_overlap(self):
        with self.assertRaisesRegex(SolverError,'overlap'):
            solve(self.mesh, self.source, self.source)
        with self.assertRaisesRegex(SolverError,'zero-volt'):
            solve(self.mesh, self.source, self.source, shared_return_contacts=True)

    def test_aliases_inside_one_unit_still_rejected_but_shared_return_is_valid(self):
        geometry={'terminals':[{'id':'a','label':'J1.1','net':'GND'}]}
        mesh={'terminal_nodes':{'a':[0,1]}}
        request={'net':'GND','source_terminals':['a'],'source_voltage':0,
                 '_shared_return_contacts':True}
        result=resolve_units(request,geometry,mesh,[{'terminals':['J1.1'],'current_A':2}])
        self.assertEqual(result[2][0]['nodes'], [0,1])
        with self.assertRaises(ValueError):
            resolve_units(request,geometry,mesh,[{'terminals':['a','J1.1'],'current_A':2}])
        value=study(); value['shared_returns'][0]['loads'][0]['terminals']=['G0']
        validate_study(value)


if __name__ == '__main__': unittest.main()
