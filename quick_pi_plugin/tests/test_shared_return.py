"""Analytical common-impedance coupling and explicit pad-unit contracts."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from quick_pi_plugin.batch import execute,validate_study,SCHEMA
from quick_pi_plugin.service import sink_requests
from quick_pi_plugin.solver import solve,SolverError
from quick_pi_plugin.terminals import resolve_units,source_names
from quick_pi_plugin.tests.test_solver import strip,combine


def study():
    return {'schema':SCHEMA,'cases':[
        {'name':name,'electrical':{'net':name,'source_terminals':['S'+name],
         'source_voltage':3.3,'sinks':[{'id':'chip','terminals':['P'+name],'current_A':current}]}}
        for name,current in [('A',1.),('B',2.)]],
        'shared_returns':[{'name':'Ground','net':'GND','source_terminals':['G0'],
            'loads':[{'case':'A','sink':'chip','terminals':['G1']},
                     {'case':'B','sink':'chip','terminals':['G2']}]}]}


class SharedReturnTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'board.kicad_pcb';self.path.write_text('(kicad_pcb)')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.mesh,self.source,self.end=strip(length=20,nx=4,ny=2)
        self.middle=[j*5+2 for j in range(3)]
        self.r=1.724e-8*.01/(.001*.000035);self.calls=[]

    def runner(self,request):
        self.calls.append(request)
        specs=[{**s,'nodes':self.middle if request['net']=='GND' and i==0 else self.end}
               for i,s in enumerate(request['sinks'])]
        return {'result':solve(self.mesh,self.source,source_voltage=request['source_voltage'],
                               sinks=specs,source_current_limit=request.get('source_current_limit')),
                'source_sha256':self.sha}

    def run_study(self,value=None,runner=None):
        return execute({'board_path':str(self.path),'study':value or study()},runner or self.runner)['batch']

    def test_common_impedance_exact_transfer_matrix_power_and_one_ground_solve(self):
        value=study();original=copy.deepcopy(value);result=self.run_study(value)
        self.assertEqual(result['status'],'COMPLETED');self.assertEqual(value,original)
        self.assertEqual([r['net'] for r in self.calls],['A','B','GND'])
        ground=result['shared_returns'][0];a,b=ground['loads']
        # Exact R matrix of two series sheet sections: [[R,R],[R,2R]].
        self.assertAlmostEqual(a['ground_rise_V'],3*self.r,11)
        self.assertAlmostEqual(b['ground_rise_V'],5*self.r,11)
        self.assertAlmostEqual(ground['return_loss_W'],(3**2+2**2)*self.r,11)
        self.assertAlmostEqual(a['delivered_load_voltage_V'],3.3-5*self.r,11)
        self.assertAlmostEqual(b['delivered_load_voltage_V'],3.3-9*self.r,11)
        self.assertLess(ground['power_balance_error_W'],1e-10)
        raw=ground['return_conduction']['result']
        self.assertLess(raw['current_balance_error_A'],1e-10)
        self.assertAlmostEqual(raw['source_current_A'],3.,10)
        self.assertAlmostEqual(ground['physical_return_potential_V'][self.end[0]],b['ground_rise_V'],12)
        # Independent ground losses omit 2*I_A*I_B*R, the coupling cross term.
        self.assertAlmostEqual(ground['return_loss_W']-(1+2*4)*self.r,4*self.r,11)

    def test_nonzero_offdiagonal_response_and_linear_superposition(self):
        def run(a,b):
            value=study()
            for case,current in zip(value['cases'],(a,b)):case['electrical']['sinks'][0]['current_A']=current
            return self.run_study(value)['shared_returns'][0]
        first=run(1,2);second=run(3,4);summed=run(4,6);changed=run(2,2)
        for i in range(2):
            self.assertAlmostEqual(summed['loads'][i]['ground_rise_V'],
                first['loads'][i]['ground_rise_V']+second['loads'][i]['ground_rise_V'],11)
        self.assertAlmostEqual(changed['loads'][1]['ground_rise_V']-first['loads'][1]['ground_rise_V'],self.r,11)

    def test_delivered_voltage_and_source_budget_drive_case_status(self):
        value=study();value['cases'][0]['electrical']['sinks'][0]['min_voltage_V']=3.28
        result=self.run_study(value)
        self.assertTrue(result['cases'][0]['electrical']['result']['feasibility']['feasible'])
        self.assertEqual(result['cases'][0]['status'],'INFEASIBLE')
        value=study();value['cases'][0]['electrical']['sinks'][0]['max_voltage_V']=3.28
        result=self.run_study(value)
        self.assertFalse(result['cases'][0]['electrical']['result']['feasibility']['feasible'])
        self.assertEqual(result['cases'][0]['status'],'COMPLETED')
        value['cases'][0]['electrical']['source_current_limit']=.5
        self.assertEqual(self.run_study(value)['cases'][0]['status'],'INFEASIBLE')

    def test_source_change_during_ground_discards_all_and_foreign_hash_fails_members(self):
        def changed(request):
            result=self.runner(request)
            if request['net']=='GND':self.path.write_text('changed')
            return result
        with self.assertRaisesRegex(ValueError,'every case'):self.run_study(runner=changed)
        self.path.write_text('(kicad_pcb)')
        def foreign(request):
            result=self.runner(request)
            if request['net']=='GND':result['source_sha256']='foreign'
            return result
        result=self.run_study(runner=foreign)
        self.assertTrue(all(row['status']=='FAILED' for row in result['cases']))
        self.assertNotIn('return_conduction',result['shared_returns'][0])

    def test_member_failure_never_runs_partial_return(self):
        def failed(request):
            if request['net']=='A':raise ValueError('Disconnected source')
            return self.runner(request)
        result=self.run_study(runner=failed)
        self.assertEqual([r['net'] for r in self.calls],['B'])
        self.assertTrue(all(row['status']=='FAILED' for row in result['cases']))

    def test_invalid_mappings_and_unsupported_modes_rejected(self):
        mutations=[
            lambda v:v['shared_returns'][0]['loads'].pop(),
            lambda v:v['shared_returns'][0]['loads'][0].update(sink='absent'),
            lambda v:v['shared_returns'][0]['loads'][0].update(terminals=['G0']),
            lambda v:v['shared_returns'].append(copy.deepcopy(v['shared_returns'][0])),
            lambda v:v['cases'][0]['electrical'].update(load_resistance_ohm=5),
            lambda v:v['cases'][0]['electrical'].update(model_dimension='3d'),
            lambda v:v['cases'][0]['electrical']['sinks'][0].pop('id'),
            lambda v:v['cases'][1]['electrical'].update(net='A'),
        ]
        # A group may own only case A; the omitted case B remains independent.
        mutations.pop(0)
        for mutation in mutations:
            value=study();mutation(value)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_study(value)


class PadUnitTests(unittest.TestCase):
    def test_parallel_pad_units_divide_current_by_conductance_not_equally(self):
        a,sa,ta=strip(width=1);b,sb,tb=strip(width=2,z=1)
        mesh,n=combine(a,b);source=sa+[i+n for i in sb];sink=ta+[i+n for i in tb]
        result=solve(mesh,source,sink,sink_current=3)
        # Equal J in widths 1 and 2 means 1 A and 2 A, not 1.5 A per pad.
        count=len(a['triangles'])
        ja=result['cell_J_A_mm2'][0][0];jb=result['cell_J_A_mm2'][count][0]
        self.assertAlmostEqual(ja*.035,1.,9);self.assertAlmostEqual(jb*.07,2.,9)
        self.assertLess(result['current_balance_error_A'],1e-10)

    def test_pad_resolution_aliases_wrong_net_and_overlap(self):
        mesh={'terminal_nodes':{'s':[0],'a':[1],'b':[2]}}
        geometry={'terminals':[{'id':i,'label':label,'net':'VCC'} for i,label in [('s','J1.1'),('a','U1.1'),('b','U1.2')]]}
        request={'net':'VCC','source_terminals':['s']}
        specs=sink_requests({'sinks':[{'id':'load','terminals':['a','U1.2'],'current_A':2}]})
        _,_,sinks,evidence=resolve_units(request,geometry,mesh,specs)
        self.assertEqual(sinks[0]['nodes'],[1,2]);self.assertEqual(sinks[0]['current_A'],2.)
        self.assertIn('no equal',evidence['assumption'])
        # Distinct pads in one ideal unit may share mesh vertices. Different
        # units must not share vertices, and repeated physical IDs still fail.
        shared={'terminal_nodes':{'s':[0],'a':[1,2],'b':[2,3]}}
        self.assertEqual(resolve_units(request,geometry,shared,specs)[2][0]['nodes'],[1,2,3])
        with self.assertRaisesRegex(ValueError,'overlap'):
            resolve_units(request,geometry,shared,[{'terminal':'a','current_A':1},{'terminal':'b','current_A':1}])
        for pads in (['a','U1.1'],['a','s'],['absent']):
            with self.assertRaises(ValueError):resolve_units(request,geometry,mesh,[{'terminals':pads,'current_A':1}])
        geometry['terminals'][1]['net']='OTHER'
        with self.assertRaisesRegex(ValueError,'selected net'):resolve_units(request,geometry,mesh,specs)
        with self.assertRaises(ValueError):source_names({'source_terminal':'a','source_terminals':['b']})
        with self.assertRaises(ValueError):sink_requests({'sinks':[{'terminals':['a','a'],'current_A':1}]})

    def test_disconnected_load_is_not_a_solved_equipotential_demand(self):
        a,sa,ta=strip();b,sb,tb=strip(z=1)
        mesh,n=combine(a,b)
        with self.assertRaisesRegex(SolverError,'connect'):
            solve(mesh,sa,sinks=[{'id':'remote','nodes':[i+n for i in tb],'current_A':1}])

    def test_physical_return_report_flips_fields_without_mutating_raw_evidence(self):
        from quick_pi_plugin.tests.test_report import bundle
        from quick_pi_plugin.shared_return import physical_report_bundle
        from quick_pi_plugin.report import cell_values,terminal_ids
        original=bundle();mesh=original['mesh']
        source=[i for i,p in enumerate(mesh['points_mm']) if p[0]==0]
        sink=[i for i,p in enumerate(mesh['points_mm']) if p[0]==10]
        original['result']=solve(mesh,source,sink,source_voltage=0,sink_current=2)
        before=copy.deepcopy(original)
        physical=physical_report_bundle({'return_conduction':original})
        self.assertEqual(original,before)
        self.assertGreater(physical['result']['potential_V'][sink[0]],0)
        self.assertLess(physical['result']['cell_J_A_mm2'][0][0],0)
        self.assertTrue(all(v>=0 for v in cell_values(mesh,physical['result'],'drop')))
        self.assertTrue(all(v>=0 for v in cell_values(mesh,physical['result'],'resistance')))
        self.assertEqual(physical['auxiliary_reversed_current_result'],original['result'])
        self.assertEqual(terminal_ids({'source_terminals':['s1','s2'],'sinks':[{'terminals':['a','b']}]}),{'s1','s2','a','b'})


if __name__=='__main__':unittest.main()
