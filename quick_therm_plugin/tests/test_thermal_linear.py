import unittest
import numpy as np
from scipy.sparse import csr_matrix, diags
from wayricad_runtime.thermal_linear import solve_thermal_linear


class ThermalLinearTests(unittest.TestCase):
    def test_large_conductance_contrast_retains_analytical_temperatures(self):
        matrix = diags([1e-18, 1e-9, 1, 1e9, 1e18], format='csr')
        expected = np.array([20., 30., 40., 50., 60.])
        np.testing.assert_allclose(solve_thermal_linear(matrix, matrix @ expected), expected, rtol=1e-12)

    def test_coupled_network_obeys_node_energy_equations(self):
        matrix = csr_matrix([[3., -2., 0.], [-2., 6., -3.], [0., -3., 4.]])
        rhs = np.array([1., 0., 2.])
        solved = solve_thermal_linear(matrix, rhs)
        np.testing.assert_allclose(matrix @ solved, rhs, atol=1e-12)

    def test_singular_and_nonfinite_inputs_are_actionable(self):
        with self.assertRaisesRegex(ValueError, 'singular|conditioned'):
            solve_thermal_linear(csr_matrix([[1., -1.], [-1., 1.]]), np.array([1., 0.]))
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            solve_thermal_linear(diags([float('nan')], format='csr'), np.array([1.]))
