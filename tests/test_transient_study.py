"""Transient worker/CLI/report boundaries and saved-source provenance."""
import contextlib
import copy
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from matplotlib.figure import Figure
from wayricad_runtime.transient_study import execute_study,draw_study,write_study_report


ROOT=Path(__file__).resolve().parents[1]


def fixture(kind):
    folder='quick_pi_plugin' if kind=='pi' else 'quick_therm_plugin'
    name='transient-load-step.json' if kind=='pi' else 'transient-power-step.json'
    return json.loads((ROOT/folder/'studies'/name).read_text())


class TransientStudyBoundaryTests(unittest.TestCase):
    def test_workers_run_explicit_models_without_native_board_bindings(self):
        from quick_pi_plugin.service import execute as pi
        from quick_therm_plugin.service import execute as thermal
        for kind,execute in [('pi',pi),('thermal',thermal)]:
            request={'action':'transient','study':fixture(kind)};before=copy.deepcopy(request)
            result=execute(request)
            self.assertIn('times_s',result['transient']);self.assertEqual(result['study'],request['study'])
            self.assertIsNone(result['source_sha256']);self.assertEqual(request,before)
            json.dumps(result,allow_nan=False)
            figure=Figure();draw_study(figure,result)
            self.assertEqual(len(figure.axes),2)

    def test_changed_saved_source_rejected_before_and_after_solve(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_bytes(b'original')
            sha=hashlib.sha256(b'original').hexdigest()
            request={'study':{},'board_path':str(source),'source_sha256':sha}
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Reload'):execute_study(request,lambda _:self.fail('solver ran'))
            source.write_bytes(b'original')
            def mutate(_):source.write_bytes(b'changed');return {}
            with self.assertRaisesRegex(ValueError,'during'):execute_study(request,mutate)

    def test_report_is_offline_and_protects_source_and_input_companion(self):
        from quick_therm_plugin.service import execute
        bundle=execute({'action':'transient','study':fixture('thermal')})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'board.kicad_pcb';source.write_bytes(b'original')
            bundle.update(board_path=str(source),source_sha256=hashlib.sha256(b'original').hexdigest())
            paths=write_study_report(root/'thermal.html',bundle)
            self.assertIn('data:image/png;base64,',Path(paths['html']).read_text())
            self.assertEqual(json.loads(Path(paths['json']).read_text())['study'],bundle['study'])
            input_path=root/'protected.json';input_path.write_bytes(b'input')
            bundle['study_input_path']=str(input_path)
            with self.assertRaisesRegex(ValueError,'overwrite'):write_study_report(root/'protected.html',bundle)
            self.assertEqual(input_path.read_bytes(),b'input')
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):write_study_report(root/'stale.html',bundle)
            self.assertFalse((root/'stale.html').exists())

    def test_both_clis_use_transient_worker_and_reject_ignored_options(self):
        from quick_pi_plugin.cli import main as pi
        from quick_therm_plugin.cli import main as thermal
        for kind,main,folder,wrong in [('pi',pi,'quick_pi_plugin','--voltage'),('thermal',thermal,'quick_therm_plugin','--ambient')]:
            with tempfile.TemporaryDirectory() as directory:
                source=Path(directory)/'input.json';source.write_text(json.dumps(fixture(kind)))
                target=Path(directory)/'output.json'
                def run(request,timeout):
                    return execute_study(request,lambda spec:{'times_s':[0.],'feasibility':{'feasible':False}})
                with patch(folder+'.service.run_job',side_effect=run) as worker,contextlib.redirect_stdout(StringIO()):
                    self.assertEqual(main(['--transient',str(source),'--output',str(target)]),4)
                    self.assertEqual(worker.call_args.args[0]['action'],'transient')
                    self.assertEqual(main(['--transient',str(source),wrong,'25']),2)
                    self.assertEqual(main(['--transient',str(source),'--output',str(source)]),2)
                    self.assertEqual(main(['--transient',str(source),'--html',str(source.with_suffix('.html'))]),2)
                    report=Path(directory)/'report.html'
                    self.assertEqual(main(['--transient',str(source),'--html',str(report),'--output',str(report)]),2)
                self.assertEqual(json.loads(source.read_text()),fixture(kind))
                self.assertFalse(source.with_suffix('.html').exists())

    def test_capacity_and_resistance_prefill_keeps_unknowns(self):
        from quick_pi_plugin.transient_inputs import initial_study as pi
        from quick_therm_plugin.transient_inputs import initial_study as thermal
        model=pi({'sinks':[{'terminal':'A','current_A':1.},{'terminal':'B','current_A':2.}]})
        self.assertIsNone(model['source_resistance_ohm'])
        self.assertTrue(all(row['capacitance_F'] is None for row in model['loads']))
        component={'reference':'U1','power_w':2.,'resistance_k_per_w':10.}
        known=thermal({'quick_therm':{'environment':'air','components':[component]}})
        self.assertEqual(known['components'][0]['resistance_K_W'],10.)
        self.assertIsNone(known['components'][0]['capacitance_J_K'])
        for mode in ('vacuum','unknown'):
            self.assertIsNone(thermal({'quick_therm':{'environment':mode,'components':[component]}})['components'][0]['resistance_K_W'])
        self.assertIsNone(thermal({'quick_therm':{'environment':'air','components':[{**component,'heatsink':{}}]}})['components'][0]['resistance_K_W'])


if __name__=='__main__':unittest.main()
