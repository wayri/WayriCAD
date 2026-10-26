"""Analytical action, geometry, scaling and unavailable-screen acceptance."""
import copy
import math
import unittest
import numpy as np
from quick_pi_plugin.fusing import material_screen, local_screen, _CP
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip, combine
from quick_pi_plugin.tests.test_report import bundle
from quick_pi_plugin.report import cell_values, inspection_record
from quick_pi_plugin.live_current import LiveCurrentModel


class FusingTests(unittest.TestCase):
    def model(self,alpha=.00393,initial=20.,**options):
        return material_screen({'resistivity_at_20C_ohm_m':1.724e-8,'temperature_coefficient':alpha},
                               {'ambient_c':initial,'density_kg_m3':8960.,'pulse_duration_s':.1},options)

    def test_action_matches_independent_adaptive_integral_and_latent_heat(self):
        from scipy.integrate import quad
        model=self.model()
        def integrand(c):
            cp=np.interp(c+273.15,[t for t,_ in _CP],[v for _,v in _CP])/.063546
            return 8960*cp/(1.724e-8*(1+.00393*(c-20)))*1e-12
        reference=quad(integrand,20,1084.62,points=[t-273.15 for t,_ in _CP if 293.15<t<1357.77],epsabs=1e-9,epsrel=1e-11)[0]
        self.assertAlmostEqual(model['onset_action_A2s_mm4'],reference,places=9)
        latent=8960*206750/(1.724e-8*(1+.00393*(1084.62-20)))*1e-12
        self.assertAlmostEqual(model['melt_action_A2s_mm4']-reference,latent,places=9)
        # Independent NIST enthalpy: 29.660 kJ/mol from 298.15 to 1358 K.
        constant=self.model(alpha=0,initial=25,melting_temperature_c=1084.85)
        reference=8960*(29660/.063546)/1.724e-8*1e-12
        self.assertLess(abs(constant['onset_action_A2s_mm4']/reference-1),.003)

    def test_inverse_square_time_and_section_squared_i2t(self):
        model=self.model();a=local_screen(model,100,.025);b=local_screen(model,200,.05)
        self.assertAlmostEqual(a['time_to_melt_s'],4*b['time_to_melt_s'])
        self.assertAlmostEqual(b['i2t_to_melt_A2s'],4*a['i2t_to_melt_A2s'])
        self.assertLess(a['time_to_onset_s'],a['time_to_melt_s'])
        self.assertAlmostEqual(a['i2t_to_melt_A2s'],(100*.025)**2*a['time_to_melt_s'])
        self.assertEqual(local_screen(model,0)['pulse_melt_ratio'],0)
        self.assertIsNone(local_screen(model,0)['time_to_melt_s'])

    def test_invalid_and_out_of_range_inputs_do_not_create_false_times(self):
        for options in ({'latent_heat_J_kg':-1},{'latent_heat_J_kg':True},{'melting_temperature_c':float('nan')},{'melting_temperature_c':10}):
            with self.subTest(options=options),self.assertRaises(ValueError):self.model(**options)
        for model in (self.model(initial=-40),self.model(melting_temperature_c=1200),self.model(alpha=-.01),self.model(alpha=1000)):
            self.assertEqual(model['status'],'unavailable')
            self.assertIsNone(local_screen(model,100)['time_to_melt_s'])
        mesh,source,sink=strip()
        result=solve(mesh,source,sink,options={'ambient_c':-40})
        self.assertGreater(result['total_power_W'],0)
        self.assertEqual(result['fusing']['status'],'unavailable')
        b=bundle();b['result'].pop('fusing')
        self.assertTrue(np.isnan(cell_values(b['mesh'],b['result'],'melt')).all())

    def test_via_i2t_uses_actual_solved_barrel_area(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1.6)
        mesh,n=combine(a,b)
        mesh['vias']=[{'id':'v1','top_nodes':ta,'bottom_nodes':[i+n for i in sb],
                       'length_mm':1.6,'drill_mm':.3,'plating_mm':.025,'top_layer':0,'bottom_layer':1.6}]
        result=solve(mesh,sa,[i+n for i in tb],sink_current=2,options={'pulse_duration_s':.1})
        row=next(r for r in result['fusing']['bottlenecks'] if r['kind']=='via')
        area=math.pi*.025*(.3+.025)
        self.assertAlmostEqual(row['cross_section_mm2'],area,places=12)
        self.assertAlmostEqual(row['i2t_to_melt_A2s'],area**2*result['fusing']['melt_action_A2s_mm4'],places=10)
        self.assertAlmostEqual(row['i2t_to_melt_A2s'],4*row['time_to_melt_s'],places=10)

    def test_distinct_series_necks_remain_discoverable_with_native_sections(self):
        parts=[strip(width=w) for w in (1.,.25,.5)]
        mesh={'points_mm':[],'triangles':[],'triangle_thickness_mm':[],'triangle_layer':[],'vias':[],'lumped_branches':[],
              'geometry':{'layers':[{'id':0,'name':'F.Cu'}],'mesh_features':[]}}
        terminals=[]
        for k,((part,source,sink),width) in enumerate(zip(parts,(1.,.25,.5))):
            n=len(mesh['points_mm'])
            mesh['points_mm'] += [[x+k*20,y,z] for x,y,z in part['points_mm']]
            mesh['triangles'] += [[i+n for i in t] for t in part['triangles']]
            mesh['triangle_thickness_mm']+=part['triangle_thickness_mm'];mesh['triangle_layer'] += [0]*len(part['triangles'])
            terminals.append(([i+n for i in source],[i+n for i in sink]))
            mesh['geometry']['mesh_features'].append({'kind':'track','id':str(k),'layer':0,'width_mm':width,
                                                     'start_mm':[k*20,width/2],'end_mm':[k*20+10,width/2]})
        for k in range(2):mesh['lumped_branches'].append({'id':str(k),'top_nodes':terminals[k][1],'bottom_nodes':terminals[k+1][0],'resistance_ohm':0})
        result=solve(mesh,terminals[0][0],terminals[-1][1],sink_current=2)
        rows=result['fusing']['bottlenecks']
        self.assertEqual(rows[0]['source_ids'],['1'])
        self.assertTrue(any(row['source_ids']==['2'] for row in rows))
        self.assertLess(len(rows),len(result['cell_J_A_mm2']))
        for row in rows:
            if row['source_ids']==['1']:self.assertAlmostEqual(row['cross_section_mm2'],.25*.035)

    def test_live_current_matches_fresh_fusing_and_melt_fields(self):
        b=bundle();b['model']='2.5D DC copper conduction; layered sheets and plated barrels'
        b['request'].update(action='solve',sink_current=2,options={'pulse_duration_s':1})
        original=copy.deepcopy(b['result']['fusing'])
        scaled=LiveCurrentModel(b).update(4)
        fresh=solve(b['mesh'],[i for i,p in enumerate(b['mesh']['points_mm']) if p[0]==0],
                    [i for i,p in enumerate(b['mesh']['points_mm']) if p[0]==10],sink_current=4,options={'pulse_duration_s':1})
        self.assertAlmostEqual(scaled['result']['fusing']['bottlenecks'][0]['time_to_melt_s'],fresh['fusing']['bottlenecks'][0]['time_to_melt_s'])
        np.testing.assert_allclose(cell_values(b['mesh'],scaled['result'],'melt'),cell_values(b['mesh'],fresh,'melt'),rtol=1e-10)
        self.assertEqual(b['result']['fusing'],original)
        row=inspection_record(scaled,'sheet',0,'melt')
        self.assertEqual(row['unit'],'ratio')
        self.assertIsNotNone(row['fusing']['time_to_melt_s'])

    def test_full3d_is_explicitly_unavailable(self):
        from quick_pi_plugin.full3d import solve_volume
        mesh={'points_mm':[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],'tetrahedra':[[0,1,2,3]]}
        result=solve_volume(mesh,[0],[1])
        self.assertEqual(result['fusing']['status'],'unavailable')
        self.assertEqual(result['fusing']['bottlenecks'],[])

    def test_cli_forwards_melting_inputs_and_keeps_screen_in_summary(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from quick_pi_plugin.cli import main
        output=io.StringIO()
        with patch('quick_pi_plugin.service.run_job',return_value=bundle()) as worker,contextlib.redirect_stdout(output):
            status=main(['synthetic.kicad_pcb','--net','GND','--source','A','--sink','B','--pulse','.01',
                         '--melting-temperature','1000','--latent-heat','200000'])
        self.assertEqual(status,0)
        options=worker.call_args.args[0]['options']
        self.assertEqual(options['melting_temperature_c'],1000)
        self.assertEqual(options['latent_heat_J_kg'],200000)
        self.assertIn('fusing',json.loads(output.getvalue())['result'])
        with patch('quick_pi_plugin.service.run_job') as worker,contextlib.redirect_stdout(io.StringIO()):
            status=main(['synthetic.kicad_pcb','--model-dimension','3d','--melting-temperature','1000'])
        self.assertEqual(status,2)
        worker.assert_not_called()
