"""Analytical DC acceptance cases; no KiCad or layout mocks are involved."""
import math
import unittest
import numpy as np
from quick_pi_plugin.solver import solve, SolverError


def strip(length=10., width=1., nx=10, ny=2, z=0., thickness=.035):
    points = [[length*i/nx, width*j/ny, z] for j in range(ny+1) for i in range(nx+1)]
    triangles = []
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i; b=a+1; c=a+nx+1; d=c+1
            triangles.extend(([a,b,d], [a,d,c]))
    return {'points_mm': points, 'triangles': triangles,
            'triangle_thickness_mm': [thickness]*len(triangles),
            'triangle_layer': [z]*len(triangles), 'vias': []}, \
           [j*(nx+1) for j in range(ny+1)], [j*(nx+1)+nx for j in range(ny+1)]


def combine(a, b):
    n=len(a['points_mm'])
    return {'points_mm': a['points_mm']+b['points_mm'],
            'triangles': a['triangles']+[[v+n for v in t] for t in b['triangles']],
            'triangle_thickness_mm': a['triangle_thickness_mm']+b['triangle_thickness_mm'],
            'triangle_layer': a['triangle_layer']+b['triangle_layer'], 'vias': []}, n


class AnalyticalSolverTests(unittest.TestCase):
    def test_uniform_strip_exact_resistance_voltage_density_power(self):
        mesh, source, sink=strip()
        r=solve(mesh,source,sink,sink_current=2.)
        resistance=1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(r['drop_over_current_ohm'],resistance,12)
        self.assertAlmostEqual(r['voltage_drop_V'],2*resistance,12)
        self.assertAlmostEqual(r['total_power_W'],4*resistance,12)
        self.assertLess(r['energy_relative_error'],1e-12)
        self.assertLess(r['current_balance_error_A'],1e-10)
        for density in r['cell_J_A_mm2']:
            self.assertAlmostEqual(density[0],2/.035,8)
            self.assertAlmostEqual(density[1],0,8)

    def test_parallel_layers_share_current_by_conductance(self):
        a,sa,ta=strip(); b,sb,tb=strip(width=2,z=1)
        mesh,n=combine(a,b)
        r=solve(mesh,sa+[i+n for i in sb],ta+[i+n for i in tb],sink_current=3.)
        resistance=1.724e-8*.01/(.003*.000035)
        self.assertAlmostEqual(r['drop_over_current_ohm'],resistance,12)
        for density in r['cell_J_A_mm2']: self.assertAlmostEqual(density[0],1/.035,8)

    def test_via_barrel_in_series_exact_ohms_current_joule_loss(self):
        a,sa,ta=strip(); b,sb,tb=strip(z=1.6)
        mesh,n=combine(a,b)
        mesh['vias']=[{'id':'v1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                       'length_mm':1.6,'drill_mm':.3,'plating_mm':.025}]
        r=solve(mesh,sa,[i+n for i in tb],sink_current=2.)
        via_r=1.724e-8*.0016/(math.pi*.025*(.3+.025)*1e-6)
        strip_r=1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(r['drop_over_current_ohm'],2*strip_r+via_r,12)
        self.assertAlmostEqual(r['vias'][0]['current_A'],2.,10)
        self.assertAlmostEqual(r['vias'][0]['power_W'],4*via_r,12)

    def test_mesh_refinement_and_winding_preserve_linear_solution(self):
        values=[]
        for nx,ny in ((1,1),(10,2),(30,6)):
            mesh,source,sink=strip(nx=nx,ny=ny)
            mesh['triangles']=[t[::-1] for t in mesh['triangles']]
            values.append(solve(mesh,source,sink)['drop_over_current_ohm'])
        self.assertLess(max(values)-min(values),1e-12)

    def test_scaling_voltage_only_shifts_potential(self):
        mesh,s,t=strip()
        a=solve(mesh,s,t,source_voltage=1); b=solve(mesh,s,t,source_voltage=12)
        self.assertEqual(a['cell_J_A_mm2'],b['cell_J_A_mm2'])
        np.testing.assert_allclose(np.array(b['potential_V'])-a['potential_V'],11)

    def test_spreading_contact_resistance_converges_with_refinement(self):
        # Restricted opposite-corner electrodes create a non-linear potential
        # field and current crowding; uniform-strip exactness cannot test this.
        values=[]
        for size in (8,16,32,64):
            mesh,s,t=strip(length=2,width=2,nx=size,ny=size)
            s=[i for i in s if mesh['points_mm'][i][1]<=.5]
            t=[i for i in t if mesh['points_mm'][i][1]>=1.5]
            r=solve(mesh,s,t); values.append(r['drop_over_current_ohm'])
            self.assertLess(r['energy_relative_error'],1e-8)
        increments=np.diff(values)
        self.assertTrue(np.all(increments>0))
        self.assertLess(increments[2],.6*increments[1])
        self.assertLess(increments[1],.6*increments[0])

    def test_disconnected_load_is_explicit_failure(self):
        a,sa,ta=strip(); b,sb,tb=strip(z=1)
        mesh,n=combine(a,b)
        with self.assertRaisesRegex(SolverError,'disconnected'): solve(mesh,sa,[i+n for i in tb])

    def test_floating_copper_has_unknown_potentials_and_no_fake_current(self):
        a,sa,ta=strip(); b,_,_=strip(z=1)
        mesh,n=combine(a,b); r=solve(mesh,sa,ta)
        self.assertEqual(r['floating_nodes'],len(b['points_mm']))
        self.assertTrue(all(v is None for v in r['potential_V'][n:]))
        self.assertTrue(all(j is None for j in r['cell_J_A_mm2'][len(a['triangles']):]))

    def test_overlap_and_malformed_geometry_rejected(self):
        mesh,s,t=strip()
        with self.assertRaisesRegex(SolverError,'overlap'): solve(mesh,s,s)
        mesh['triangles'][0]=[0,0,0]
        with self.assertRaisesRegex(SolverError,'Degenerate'): solve(mesh,s,t)

    def test_adiabatic_thermal_budget_and_temperature_resistivity(self):
        mesh,s,t=strip()
        r=solve(mesh,s,t,options={'temperature_c':70,'pulse_duration_s':10,'ambient_c':20,'temperature_limit_c':100})
        self.assertAlmostEqual(r['material']['resistivity_ohm_m'],1.724e-8*(1+.00393*50),16)
        cell=r['cell_thermal'][0]
        self.assertAlmostEqual(cell['energy_ratio'],10/cell['time_to_limit_s'],12)
        self.assertIn('adiabatic',cell['status'])

    def test_missing_pulse_duration_is_reported(self):
        mesh,s,t=strip(); r=solve(mesh,s,t)
        self.assertEqual(r['cell_thermal'][0]['status'],'pulse_duration_required')
        self.assertIsNone(r['cell_thermal'][0]['energy_ratio'])

    def test_excess_pulse_energy_is_flagged_and_result_serializes(self):
        import json
        mesh,s,t=strip(); mesh['triangle_layer']=np.zeros(len(mesh['triangles']),dtype=np.int64)
        r=solve(mesh,s,t,sink_current=100,options={'pulse_duration_s':60})
        self.assertEqual(r['cell_thermal'][0]['status'],'temperature_limit_exceeded_adiabatic')
        self.assertGreater(r['cell_thermal'][0]['energy_ratio'],1)
        json.dumps(r,allow_nan=False)

    def test_unsupplied_voltage_warns_negative_sink_instead_of_clipping(self):
        mesh,s,t=strip(); r=solve(mesh,s,t,source_voltage=.001,sink_current=100)
        self.assertTrue(r['negative_sink_voltage'])
        self.assertLess(r['sink_voltage_V'],0)

    def test_series_resistor_and_inductor_across_copper_domains(self):
        a,sa,ta=strip(); b,sb,tb=strip(z=1)
        mesh,n=combine(a,b)
        mesh['lumped_branches']=[{'id':'L1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                                 'resistance_ohm':.1,'inductance_h':1e-6}]
        r=solve(mesh,sa,[i+n for i in tb],sink_current=2)
        copper_r=2*1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(r['drop_over_current_ohm'],copper_r+.1,11)
        component=r['components'][0]
        self.assertAlmostEqual(component['current_A'],2,10)
        self.assertAlmostEqual(component['voltage_drop_V'],.2,10)
        self.assertAlmostEqual(component['power_W'],.4,10)
        self.assertAlmostEqual(component['magnetic_energy_J'],2e-6,12)
        self.assertAlmostEqual(r['conductor_power_W'],4*copper_r,11)
        self.assertAlmostEqual(r['component_power_W'],.4,10)

    def test_ideal_inductor_short_tree_current_is_recovered(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1);mesh,n=combine(a,b)
        mesh['lumped_branches']=[{'id':'L1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                                 'resistance_ohm':0,'inductance_h':2e-6}]
        r=solve(mesh,sa,[i+n for i in tb],sink_current=3)
        c=r['components'][0]
        self.assertAlmostEqual(c['current_A'],3,10)
        self.assertEqual(c['power_W'],0)
        self.assertAlmostEqual(c['magnetic_energy_J'],9e-6,12)

    def test_ideal_inductor_parallel_loop_has_no_invented_current(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1);mesh,n=combine(a,b)
        mesh['lumped_branches']=[{'id':name,'top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                                 'resistance_ohm':0,'inductance_h':2e-6} for name in ('L1','L2')]
        r=solve(mesh,sa,[i+n for i in tb])
        self.assertTrue(all(c['current_status']=='indeterminate_ideal_short_loop' for c in r['components']))
        self.assertTrue(all(c['magnetic_energy_J'] is None for c in r['components']))

    def test_negative_component_values_are_rejected(self):
        mesh,s,t=strip();mesh['lumped_branches']=[{'top_nodes':s,'bottom_nodes':t,'resistance_ohm':-1}]
        with self.assertRaisesRegex(SolverError,'resistance'):solve(mesh,s,t)

    def test_skinny_equipotential_cells_do_not_leak_a_domain_offset(self):
        # These extremely thin cells all lie within an ideal component contact.
        # Their nine stiffness terms must condense to exactly zero; naïve
        # stamping creates a fictitious shunt that corrupts the series current.
        a,sa,ta=strip();b,sb,tb=strip(z=1);mesh,n=combine(a,b)
        contact=[i+n for i in sb]
        for index in range(200):
            start=len(mesh['points_mm']);x=200+index*.001
            mesh['points_mm'].extend([[x,200,1],[x+1e-6,200.01,1],[x,200.010001,1]])
            mesh['triangles'].append([start,start+1,start+2]);mesh['triangle_thickness_mm'].append(.035)
            mesh['triangle_layer'].append(1);contact.extend([start,start+1,start+2])
        mesh['lumped_branches']=[{'id':'R1','top_nodes':ta,'bottom_nodes':contact,'resistance_ohm':.005}]
        r=solve(mesh,sa,[i+n for i in tb])
        self.assertAlmostEqual(r['components'][0]['current_A'],1,11)
        self.assertLess(r['energy_relative_error'],1e-10)
        self.assertLess(r['current_balance_error_A'],1e-10)


if __name__=='__main__': unittest.main()
