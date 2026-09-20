import unittest,math
import numpy as np
from planar_magnetics_plugin.capacitance import solve_interwinding,adjacent_round_wire,estimate_pcb_sidewall,EPS0

def winding(ri,ro,h,z=0):return dict(winding_inner_mm=ri,winding_outer_mm=ro,winding_height_mm=h,z_offset_mm=z)
class CapacitanceTests(unittest.TestCase):
    def test_coaxial_known_answer_and_refinement(self):
        p,s=winding(.5,1,10),winding(2,2.5,10)
        expected=2*math.pi*EPS0*3*.01/math.log(2)
        errors=[]
        for n in (16,32,64):
            r=solve_interwinding(p,s,epsilon_r=3,domain_radius_mm=3,domain_half_height_mm=5,radial_cells=n,axial_cells=16,axial_boundary='insulated')
            errors.append(abs(r['interwinding_F']/expected-1))
            self.assertLess(r['evidence']['energy_relative_error'],1e-9)
        self.assertLess(errors[2],errors[1]);self.assertLess(errors[1],errors[0]);self.assertLess(errors[2],.0005)
    def test_maxwell_branch_mapping_scaling_and_symmetry(self):
        args=dict(primary=winding(2,3,4),secondary=winding(4,5,4),domain_radius_mm=20,domain_half_height_mm=20,radial_cells=40,axial_cells=80)
        a=solve_interwinding(**args,epsilon_r=1);b=solve_interwinding(**args,epsilon_r=4)
        c=np.array(a['C_matrix_F'])
        np.testing.assert_allclose(c,c.T,rtol=1e-10)
        self.assertGreater(np.linalg.eigvalsh(c).min(),0)
        self.assertAlmostEqual(c[0,0],a['interwinding_F']+a['primary_environment_F'],places=23)
        self.assertAlmostEqual(c[1,1],a['interwinding_F']+a['secondary_environment_F'],places=23)
        np.testing.assert_allclose(b['C_matrix_F'],4*c,rtol=1e-10)
        swapped=solve_interwinding(**{**args,'primary':args['secondary'],'secondary':args['primary']},epsilon_r=1)
        np.testing.assert_allclose(swapped['C_matrix_F'],c[::-1,::-1],rtol=1e-9)
    def test_invalid_geometry_and_dielectric(self):
        args=dict(primary=winding(2,3,4),secondary=winding(2.5,4,4),domain_radius_mm=20,domain_half_height_mm=20,epsilon_r=1)
        with self.assertRaises(ValueError):solve_interwinding(**args)
        with self.assertRaises(ValueError):solve_interwinding(**{**args,'epsilon_r':None})
    def test_round_wire_energy_mapping(self):
        r=adjacent_round_wire(turns=10,wire_diameter_mm=.5,pitch_mm=1,mean_turn_length_mm=100,epsilon_r=2)
        pair=math.pi*EPS0*2*.1/math.acosh(2)
        self.assertAlmostEqual(r['adjacent_pair_F']/pair,1)
        # 9 adjacent capacitors, each sees V/10; 2E/V² = 9*Cpair/100.
        self.assertAlmostEqual(r['terminal_capacitance_F']/pair,.09)
    def test_domain_sensitivity_at_fixed_local_spacing(self):
        values=[]
        for domain,cells in ((10,24),(20,48),(30,72)):
            r=solve_interwinding(winding(2,3,4),winding(4,5,4),epsilon_r=2,domain_radius_mm=domain,domain_half_height_mm=domain,radial_cells=cells,axial_cells=2*cells)
            values.append(r['interwinding_F'])
            self.assertGreater(r['secondary_environment_F'],0)
        self.assertLess(abs(values[2]-values[1]),abs(values[1]-values[0]))
        self.assertLess(abs(values[2]/values[1]-1),.01)
    def test_sidewall_integrated_voltage_energy(self):
        from types import SimpleNamespace
        from planar_magnetics_plugin.analysis import WindingSegment
        result=SimpleNamespace(spec=SimpleNamespace(copper_um=35,spacing_mm=1,shape='Rectangular spiral'),segments=[WindingSegment(0,0,10,0,1,0),WindingSegment(10,0,10,2,1,0),WindingSegment(10,2,0,2,1,0)])
        r=estimate_pcb_sidewall(result,epsilon_r=2)
        pair=EPS0*2*35e-6*.01/.001
        expected=pair*(1+1/11+1/121)/3
        self.assertAlmostEqual(r['terminal_capacitance_F']/expected,1,places=10)
        self.assertEqual(r['coverage'],'PARTIAL_SIDEWALL_ONLY')
        result.segments.append(WindingSegment(0,2,0,0,1,1))
        with self.assertRaises(ValueError):estimate_pcb_sidewall(result,epsilon_r=2)
if __name__=='__main__':unittest.main()
