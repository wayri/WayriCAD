"""Independent reference verification through the production VTK mesher."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('numpy','scipy','vtk','matplotlib')),
                     'Reference suite requires the Quick PI scientific runtime')
class ReferenceBenchmarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from quick_pi_plugin.verification import run_benchmarks
        cls.report=run_benchmarks()

    def test_known_answers_and_conservation(self):
        self.assertTrue(self.report['pass'],json.dumps(self.report,indent=2))
        self.assertEqual(len(self.report['cases']),8)
        json.dumps(self.report,allow_nan=False)

    def test_published_circuit_operating_point(self):
        case=next(c for c in self.report['cases'] if c['name']=='elmer_published_beam_and_circuit')
        self.assertTrue(case['pass'])
        self.assertAlmostEqual(case['checks']['beam_right_voltage_V']['computed'],1.,7)
        self.assertAlmostEqual(case['checks']['power_W']['computed'],3.,7)
        self.assertTrue(case['checks']['ground_voltage_V']['pass'])

    def test_annular_absolute_accuracy_improves(self):
        cases=[c for c in self.report['cases'] if c['name'].startswith('annulus_')]
        self.assertEqual([c['contour_segments'] for c in cases],[24,48,96])
        self.assertLess(cases[-1]['checks']['resistance_ohm']['relative_error'],.002)
        self.assertLess(cases[-1]['checks']['J_vector_L2']['relative_error'],.025)
        self.assertTrue(all(self.report['annulus_refinement'].values()))

    def test_failure_is_not_reported_as_success(self):
        from quick_pi_plugin.verification import main
        with patch('quick_pi_plugin.verification.run_benchmarks',side_effect=RuntimeError('mesher unavailable')):
            with patch('builtins.print') as output:
                self.assertEqual(main([]),2)
                self.assertFalse(json.loads(output.call_args.args[0])['pass'])

    def test_cli_output_validation_and_parent_creation(self):
        from quick_pi_plugin.verification import main
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'nested'/'report.json'
            with patch('quick_pi_plugin.verification.run_benchmarks',return_value=self.report):
                self.assertEqual(main(['--output',str(path)]),0)
                self.assertTrue(json.loads(path.read_text())['pass'])
            with patch('builtins.print') as output:
                self.assertEqual(main(['--output',str(path.with_suffix('.txt'))]),2)
                self.assertEqual(json.loads(output.call_args.args[0])['error_type'],'ValueError')
            with patch('quick_pi_plugin.verification.run_benchmarks',return_value=self.report):
                with patch('pathlib.Path.write_text',side_effect=PermissionError('denied')):
                    with patch('builtins.print') as output:
                        self.assertEqual(main(['--output',str(path)]),2)
                        self.assertEqual(json.loads(output.call_args.args[0])['error_type'],'PermissionError')


if __name__=='__main__': unittest.main()
