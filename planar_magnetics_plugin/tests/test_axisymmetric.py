import unittest
from dataclasses import replace
try:
    import scipy
except ImportError:
    scipy=None
from planar_magnetics_plugin.axisymmetric import AxisymmetricSpec,solve,analytic_air_axis_b,convergence


@unittest.skipIf(scipy is None,'Optional field solver requires SciPy')
class AxisymmetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.spec=AxisymmetricSpec();cls.result=solve(cls.spec)

    def test_air_solenoid_against_finite_analytic_reference(self):
        expected=analytic_air_axis_b(self.spec)
        self.assertLess(abs(self.result['axis_center_b_t']/expected-1),.05)

    def test_source_current_energy_and_residual(self):
        r=self.result
        self.assertAlmostEqual(r['source_ampere_turns'],100,places=9)
        self.assertAlmostEqual(r['source_work_j'],r['energy_j'],places=12)
        self.assertLess(r['relative_residual'],1e-10)
        self.assertGreater(r['inductance_h'],0)

    def test_larger_air_boundary_reduces_reference_error(self):
        bigger=solve(replace(self.spec,air_extent=5))
        expected=analytic_air_axis_b(self.spec)
        self.assertLess(abs(bigger['axis_center_b_t']-expected),abs(self.result['axis_center_b_t']-expected))

    def test_current_sign_and_quadratic_energy(self):
        r=solve(replace(self.spec,current_a=-2))
        self.assertAlmostEqual(r['axis_center_b_t'],-2*self.result['axis_center_b_t'],places=10)
        self.assertAlmostEqual(r['energy_j'],4*self.result['energy_j'],places=10)
        self.assertAlmostEqual(r['inductance_h'],self.result['inductance_h'],places=10)

    def test_linear_core_raises_inductance(self):
        core=solve(replace(self.spec,core_outer_mm=6,core_mu_r=100))
        self.assertGreater(core['inductance_h'],self.result['inductance_h'])
        self.assertIn(2,core['regions'])
        with self.assertRaises(ValueError):analytic_air_axis_b(replace(self.spec,core_outer_mm=6,core_mu_r=100))

    def test_geometric_scale_law(self):
        scale=solve(replace(self.spec,winding_inner_mm=16,winding_outer_mm=20,winding_height_mm=60,core_height_mm=60))
        self.assertAlmostEqual(scale['inductance_h']/self.result['inductance_h'],2,places=8)
        self.assertAlmostEqual(scale['axis_center_b_t']/self.result['axis_center_b_t'],.5,places=8)

    def test_convergence_evidence(self):
        report=convergence(self.spec)
        self.assertLess(report['evidence']['mesh_l_change'],.01)
        self.assertLess(report['evidence']['analytic_axis_b_relative_error'],.05)
        self.assertGreater(report['evidence']['air_l_change'],0)

    def test_invalid_geometry_refused(self):
        for changes in ({'core_outer_mm':9},{'current_a':0},{'radial_cells':10000},{'air_extent':1},{'core_mu_r':float('nan')}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):solve(replace(self.spec,**changes))


if __name__=='__main__':unittest.main()
