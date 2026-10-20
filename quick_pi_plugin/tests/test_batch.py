"""Independent case bindings, failure statuses and analytical copper loss checks."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from quick_pi_plugin.batch import SCHEMA, execute, validate_study, parse_study, initial_study
from quick_pi_plugin.electrothermal_service import validate_feedback_inputs
from quick_pi_plugin.solver import solve
from quick_pi_plugin.tests.test_solver import strip


def case(name='Rail A',current=1):
    return {'name':name,'electrical':{'net':name,'source_terminal':'J1.1','source_voltage':3.3,
            'sinks':[{'terminal':'U1.1','current_A':current}]}}


def study(*cases):return {'schema':SCHEMA,'cases':list(cases) or [case()]}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'board.kicad_pcb';self.path.write_text('(kicad_pcb)')
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.mesh,self.source,self.sink=strip(length=10,width=1,nx=4,ny=2)

    def electrical(self,request):
        return {'result':solve(self.mesh,self.source,sinks=[{'id':'load','nodes':self.sink,
            'current_A':request['sinks'][0]['current_A']}],source_voltage=request['source_voltage']),
            'source_sha256':self.sha}

    def run_cases(self,cases,runner=None,**extra):
        return execute({'board_path':str(self.path),'study':study(*cases),**extra},runner or self.electrical)

    def test_two_independent_real_fem_cases_have_squared_current_loss_and_one_binding(self):
        inputs=[case('Rail A',1),case('Rail B',2)];before=copy.deepcopy(inputs)
        bundle=self.run_cases(inputs);rows=bundle['batch']['cases']
        self.assertEqual(bundle['batch']['status'],'COMPLETED')
        self.assertEqual([row['source_sha256'] for row in rows],[self.sha,self.sha])
        a,b=[row['electrical']['result'] for row in rows]
        self.assertAlmostEqual(b['total_power_W'],4*a['total_power_W'],12)
        resistance=1.724e-8*.01/(.001*.000035)
        self.assertAlmostEqual(a['total_power_W'],resistance,10)
        self.assertAlmostEqual(b['voltage_drop_V'],2*a['voltage_drop_V'],10)
        self.assertEqual(inputs,before)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.sha)

    def test_one_failed_case_does_not_mask_or_abort_the_other(self):
        def runner(request):
            if request['net']=='Broken':raise ValueError('No connected copper')
            return self.electrical(request)
        bundle=self.run_cases([case('Broken'),case('Working')],runner)
        self.assertEqual([r['status'] for r in bundle['batch']['cases']],['FAILED','COMPLETED'])
        self.assertIn('No connected copper',bundle['batch']['cases'][0]['error'])
        self.assertEqual(bundle['batch']['status'],'INCOMPLETE')

    def test_foreign_or_changed_source_invalidates_instead_of_passing(self):
        with self.assertRaisesRegex(ValueError,'changed'):
            self.run_cases([case()],source_sha256='outdated')
        def changed(request):
            self.path.write_text('edited');return self.electrical(request)
        with self.assertRaisesRegex(ValueError,'every case'):
            self.run_cases([case()],changed)
        self.path.write_text('(kicad_pcb)')
        result=self.run_cases([case()],lambda request:{'result':{},'source_sha256':'foreign'})
        self.assertEqual(result['batch']['cases'][0]['status'],'FAILED')

    def test_input_study_change_and_cancel_discard_the_batch(self):
        source=Path(self.temp.name)/'cases.json';source.write_text('{}')
        sha=hashlib.sha256(source.read_bytes()).hexdigest()
        def changed(request):
            source.write_text('changed');return self.electrical(request)
        with self.assertRaisesRegex(ValueError,'study changed'):
            self.run_cases([case()],changed,study_input_path=str(source),study_file_sha256=sha)
        def cancelled(request):raise InterruptedError('Cancelled')
        with self.assertRaises(InterruptedError):self.run_cases([case()],cancelled)

    def test_return_unknowns_and_warnings_are_not_silent_successes(self):
        for diagnostic,expected in [({'unknown_count':1},'INCOMPLETE'),({'warning_count':1},'REVIEW_REQUIRED')]:
            item=case();item['return_path']={'return_nets':['GND'],'return_terminal_roles':{'source':'J1.2'}}
            requests=[]
            def runner(request):
                requests.append(request)
                return {'return_path':diagnostic,'source_sha256':self.sha} if request['action']=='return_path' else self.electrical(request)
            result=self.run_cases([item],runner)
            self.assertEqual(result['batch']['cases'][0]['status'],expected)
            self.assertEqual(requests[1]['return_nets'],['GND'])
            self.assertEqual(requests[1]['return_terminal_roles'],{'source':'J1.2'})
            self.assertEqual(result['batch']['status'],'INCOMPLETE')
            self.assertIn('not inferred',result['batch']['assumptions'][-1])

    def test_thermal_nonconvergence_and_infeasible_operating_point_are_explicit(self):
        for coupled,status in [({'converged':False},'INCOMPLETE'),
                ({'converged':True,'limits':{'operating_point_valid':False}},'INFEASIBLE')]:
            item=case();item['electrothermal']={'thermal_settings':{},'coupling':{}}
            def runner(request):
                if request['action']=='electrothermal':
                    self.assertTrue(request['require_explicit_thermal'])
                    self.assertEqual(request['study']['electrical'],item['electrical'])
                    return {'electrothermal':coupled}
                return self.electrical(request)
            self.assertEqual(self.run_cases([item],runner)['batch']['cases'][0]['status'],status)

    def test_converged_hot_point_replaces_cold_limit_failure_but_keeps_return_review(self):
        from quick_pi_plugin.tests.test_electrothermal import request
        from quick_pi_plugin.electrothermal import solve_electrothermal
        thermal=request()
        first=solve_electrothermal(thermal)
        maximum=(first['cold']['sink_voltage_V']+first['hot']['sink_voltage_V'])/2
        thermal['sinks'][0]['max_voltage_V']=maximum
        coupled=solve_electrothermal(thermal)
        self.assertFalse(coupled['cold']['feasibility']['feasible'])
        self.assertTrue(coupled['limits']['operating_point_valid'])
        for diagnostic,expected in [(None,'COMPLETED'),({'warning_count':1},'REVIEW_REQUIRED'),({'unknown_count':1},'INCOMPLETE')]:
            item=case(current=5);item['electrothermal']={'thermal_settings':{},'coupling':{}}
            if diagnostic is not None:item['return_path']={'return_nets':['GND']}
            def runner(value):
                if value['action']=='solve':return {'result':coupled['cold']}
                if value['action']=='electrothermal':return {'electrothermal':coupled}
                return {'return_path':diagnostic}
            self.assertEqual(self.run_cases([item],runner)['batch']['cases'][0]['status'],expected)

    def test_shape_names_modes_and_explicit_terminals_are_validated(self):
        invalid=[study(*[case(str(i)) for i in range(33)]),study(case(),case()),
            {'schema':'other','cases':[case()]},study({'name':'empty','electrical':{}}),
            study(dict(case(),electrical=dict(case()['electrical'],board_path='other'))),
            study(dict(case(),return_path={'return_nets':[]})),
            study(dict(case(),return_path={'return_nets':[{}]})),
            study(dict(case(),electrothermal={'thermal_settings':{}}))]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_study(value)
        self.assertEqual(initial_study(dict(case()['electrical'],action='solve',board_path='private'))['cases'][0]['electrical'],case()['electrical'])
        for text in (b'{"schema":"x","schema":"y","cases":[]}',b'{"schema":"wayricad.pi-batch/v1","cases":NaN}'):
            with self.assertRaises(ValueError):parse_study(text)

    def test_feedback_physics_must_be_explicit_and_finite(self):
        thermal={'thermal_settings':dict(ambient_c=20,dielectric_k_w_mk=.3,copper_k_w_mk=385,
            via_plating_mm=.025,board_h_w_m2k=5,board_emissivity=.8),
            'coupling':dict(material_temperature_range_c=[0,150],temperature_cap_c=100),
            'electrical':{'options':{'resistivity_ohm_m':1.724e-8,'temperature_coefficient':.00393}}}
        validate_feedback_inputs(thermal)
        for key in thermal['thermal_settings']:
            bad=copy.deepcopy(thermal);bad['thermal_settings'][key]=None
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,key):validate_feedback_inputs(bad)
        bad=copy.deepcopy(thermal);bad['electrical']['options'].pop('temperature_coefficient')
        with self.assertRaisesRegex(ValueError,'temperature_coefficient'):validate_feedback_inputs(bad)
        for values in ([None,None],[100,20],[0,float('nan')]):
            bad=copy.deepcopy(thermal);bad['coupling']['material_temperature_range_c']=values
            with self.assertRaisesRegex(ValueError,'material_temperature_range'):validate_feedback_inputs(bad)


if __name__=='__main__':unittest.main()
