import unittest
from dataclasses import replace
import numpy as np
from scipy.special import ellipk,ellipe
from planar_magnetics_plugin.axisymmetric import AxisymmetricSpec,solve_coupled,solve,MU0

class CoupledTests(unittest.TestCase):
    def setUp(self):
        self.spec=AxisymmetricSpec(winding_inner_mm=8,winding_outer_mm=10,winding_height_mm=6,turns=20,radial_cells=32,axial_cells=64,air_extent=5)
        self.second=dict(winding_inner_mm=8,winding_outer_mm=10,winding_height_mm=6,z_offset_mm=9,turns=30)
    def test_energy_scaling_and_reciprocity(self):
        a=solve_coupled(self.spec,self.second);L=np.array(a['L_matrix_H'])
        self.assertTrue(np.all(np.linalg.eigvalsh(L)>0));self.assertTrue(0<a['k']<1)
        np.testing.assert_allclose(L,L.T,rtol=1e-12)
        b=solve_coupled(replace(self.spec,turns=40,current_a=3),{**self.second,'turns':90})
        np.testing.assert_allclose(b['L_matrix_H'],L*np.array([[4,6],[6,9]]),rtol=1e-9)
        self.assertAlmostEqual(a['k'],b['k'],places=10)
        self.assertAlmostEqual(a['primary_short_circuit_leakage_H'],L[0,0]-L[0,1]**2/L[1,1],places=14)
        self.assertLess(a['evidence']['energy_relative_error'],1e-9)
        np.testing.assert_allclose(a['evidence']['source_ampere_turns'],[20,30],rtol=1e-12)
    def test_separation_decreases_mutual(self):
        a=solve_coupled(self.spec,self.second)
        b=solve_coupled(self.spec,{**self.second,'z_offset_mm':18})
        self.assertLess(b['mutual_H'],a['mutual_H'])
    def test_overlap_and_bad_input(self):
        for change in ({'z_offset_mm':0},{'turns':True},{'turns':1.5},{'winding_inner_mm':-1}):
            with self.assertRaises(ValueError):solve_coupled(self.spec,{**self.second,**change})
    def test_axial_reflection_preserves_inductance_matrix(self):
        # Radially nested coils are not symmetric; identical coils at +/-z are.
        # Translate the reflected system by swapping primary/secondary: finite
        # centered air boundary differs, so instead use same-radius coincident-z
        # axial mirrors at +/-9 through independent sign-offset runs.
        a=solve_coupled(self.spec,self.second)
        b=solve_coupled(self.spec,{**self.second,'z_offset_mm':-9})
        np.testing.assert_allclose(a['L_matrix_H'],b['L_matrix_H'],rtol=.003)
    def test_air_mutual_against_independent_neumann_loop_quadrature(self):
        # Uniform winding cross-section average of exact circular filament M.
        # Elliptic-integral expression is independent of the FEM weak form.
        nodes,weights=np.polynomial.legendre.leggauss(5)
        ra=.009+.001*nodes;za=.003*nodes
        rb=ra;zb=.009+.003*nodes
        reference=0.
        for i,r1 in enumerate(ra):
            for j,z1 in enumerate(za):
                for k,r2 in enumerate(rb):
                    for l,z2 in enumerate(zb):
                        m=4*r1*r2/((r1+r2)**2+(z1-z2)**2)
                        mutual=MU0*np.sqrt(r1*r2)*((2-m)*ellipk(m)-2*ellipe(m))/np.sqrt(m)
                        reference+=weights[i]*weights[j]*weights[k]*weights[l]*mutual/16*20*30
        # Larger air box reduces truncation bias; refine at fixed air extent.
        coarse=solve_coupled(replace(self.spec,air_extent=8,radial_cells=64,axial_cells=128),self.second)['mutual_H']
        fine=solve_coupled(replace(self.spec,air_extent=8,radial_cells=128,axial_cells=256),self.second)['mutual_H']
        self.assertLess(abs(fine/reference-1),.005)
        self.assertLess(abs(fine-reference),abs(coarse-reference))

if __name__=='__main__':unittest.main()
