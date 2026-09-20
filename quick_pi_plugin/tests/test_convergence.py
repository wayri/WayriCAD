"""No false convergence from one close pair, repeated meshes or invalid evidence."""
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from quick_pi_plugin.convergence import assess,run_study,summary,html_section


def sample(value,index):
    return dict(edge_mm=.5/2**index,nodes=10*4**index,triangles=8*4**index,
                voltage_drop_V=value,resistance_ohm=value,power_W=value,sheet_power_W=value,current_A=1.,
                current_error_A=0.,nodal_error_A=0.,energy_error=0.,peak_J_A_mm2=2**index)


class ConvergenceTests(unittest.TestCase):
    def test_two_final_changes_required_and_peak_not_certified(self):
        report=assess([sample(v,i) for i,v in enumerate((100,101,101.5))])
        self.assertEqual('STABLE_WITHIN_TOLERANCE',report['status'])
        self.assertTrue(report['terminal_drop_stable']);self.assertFalse(report['peak_current_converged'])
        report=assess([sample(v,i) for i,v in enumerate((90,101,101.5))])
        self.assertEqual('NOT_STABLE',report['status'])
        self.assertEqual('INCOMPLETE',assess([sample(1,0),sample(1,1)])['status'])

    def test_budget_failure_retains_incomplete_even_if_close(self):
        report=assess([sample(1,i) for i in range(3)],failure={'reason':'budget'})
        self.assertFalse(report['terminal_drop_stable']);self.assertEqual('INCOMPLETE',report['status'])

    def test_large_series_loss_cannot_hide_unstable_sheet_loss(self):
        rows=[sample(1,i) for i in range(3)]
        for i,row in enumerate(rows):row['sheet_power_W']=.001*2**i
        self.assertEqual('NOT_STABLE',assess(rows)['status'])

    def test_balance_failure_and_identical_mesh_do_not_pass(self):
        rows=[sample(1,i) for i in range(3)];rows[-1]['current_error_A']=1e-4
        self.assertEqual('BALANCE_FAILED',assess(rows)['status'])
        rows[-1]['current_error_A']=0;rows[-1]['triangles']=rows[-2]['triangles']
        self.assertEqual('MESH_NOT_REFINED',assess(rows)['status'])

    def test_invalid_or_changed_conditions(self):
        for value in (0,-1,float('nan'),float('inf'),21):
            with self.assertRaises(ValueError):assess([],value)
        for key in ('voltage_drop_V','power_W','energy_error','nodes','triangles'):
            row=sample(1,0);row[key]=float('nan')
            with self.assertRaises(ValueError):assess([row])
        rows=[sample(1,i) for i in range(3)];rows[-1]['current_A']=2
        with self.assertRaisesRegex(ValueError,'current changed'):assess(rows)

    def test_runner_fixed_inputs_partial_budget_and_saved_board_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_bytes(b'fixture')
            digest=hashlib.sha256(source.read_bytes()).hexdigest();calls=[]
            request=dict(action='converge',board_path=str(source),edge_mm=.5,options={'temperature_c':20})
            original=copy.deepcopy(request)
            def execute(req):
                calls.append(copy.deepcopy(req));i=len(calls)-1
                if i==3:raise ValueError('Mesh exceeds budget')
                s=sample(1,i)
                return {'request':req,'geometry':{'source_sha256':digest,'geometry_sha256':'same'},
                        'mesh':{'points_mm':[None]*s['nodes'],'triangles':[None]*s['triangles']},
                        'result':dict(voltage_drop_V=1.,drop_over_current_ohm=1.,total_power_W=1.,planar_power_W=1.,sink_current_A=1.,current_balance_error_A=0.,max_nodal_residual_A=0.,energy_relative_error=0.,max_current_density_A_mm2=i+1.)}
            result=run_study(request,execute)
            self.assertEqual('INCOMPLETE',result['convergence']['status']);self.assertEqual(3,len(result['convergence']['samples']))
            self.assertEqual([.5,.25,.125,.0625],[r['edge_mm'] for r in calls]);self.assertEqual(original,request)
            self.assertTrue(all(r['options']==request['options'] for r in calls))
            calls.clear()
            def changed(req):
                result=execute(req);source.write_bytes(b'changed');return result
            with self.assertRaisesRegex(ValueError,'board changed'):run_study(request,changed)

    def test_summary_and_export_keep_limits(self):
        report=assess([sample(1,i) for i in range(3)],failure={'reason':'<script>'})
        self.assertIn('Peak current is not convergence-certified',summary(report))
        html=html_section(report);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)


if __name__=='__main__':unittest.main()
