"""Input custody checks for the opt-in public example generator."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_results', ROOT / 'tools/generate_public_board_results.py')
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class PublicBoardInputs(unittest.TestCase):
    def test_failed_case_does_not_publish_partial_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / 'public.kicad_pcb'
            board.write_bytes(b'(kicad_pcb)')
            output = root / 'results'
            specification = root / 'studies.json'
            specification.write_text(json.dumps(dict(boards=[dict(id='board', filename=board.name,
                sha256=generator.sha(board))], cases=[dict(id=name, board_id='board', kind='quick-pi',
                summary='Test fixture', request={}) for name in ('first', 'second')])), encoding='utf-8')
            result = ({}, 'Quick PI', 'quick_pi_plugin', {}, None)
            with patch.dict('sys.modules', {'pcbnew': SimpleNamespace(GetBuildVersion=lambda: 'test')}), \
                 patch.object(generator, 'run_case', side_effect=[result, ValueError('fixture failure')]), \
                 patch.object(generator, 'numerical_summary', return_value={}), \
                 patch('wayricad_runtime.pocket_report.evidence_context', return_value={'version': 'test'}), \
                 patch('wayricad_runtime.pocket_kivi_export.portable_json', return_value=b'{}'):
                with self.assertRaisesRegex(ValueError, 'fixture failure'):
                    generator.generate(root, output, specification)
            self.assertEqual(list(output.iterdir()), [])

    def test_exact_bytes_and_changed_source_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'public.kicad_pcb'
            path.write_bytes(b'(kicad_pcb)')
            spec = dict(filename=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(generator.checked_board(temporary, spec), path.resolve())
            path.write_bytes(b'(kicad_pcb changed)')
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                generator.checked_board(temporary, spec)

    def test_traversal_and_unpinned_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'named PCB'):
                generator.checked_board(temporary, dict(filename='../private.kicad_pcb', sha256='a' * 64))
            with self.assertRaisesRegex(ValueError, 'pinned board'):
                generator.checked_board(temporary, dict(filename='public.kicad_pcb', sha256='unknown'))

    def test_absent_sidecar_is_recorded_and_new_sidecar_changes_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            board = Path(temporary) / 'public.kicad_pcb'
            board.write_bytes(b'(kicad_pcb)')
            before = generator.snapshots(board)
            self.assertIsNone(before['public.kicad_pro'])
            board.with_suffix('.kicad_pro').write_text('{}', encoding='utf-8')
            self.assertNotEqual(before, generator.snapshots(board))


class RetainedPublicResults(unittest.TestCase):
    def test_complete_evidence_and_numerical_checks(self):
        directory = ROOT / 'docs/examples/public-boards'
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['cases']), 6)
        for case in manifest['cases']:
            with self.subTest(case=case['id']):
                path = directory / case['result_path']
                self.assertEqual(generator.sha(path), case['result_sha256'])
                data = path.read_text(encoding='utf-8')
                self.assertIsNone(re.search(r'(?<![A-Za-z])[A-Za-z]:[\\/]', data),
                                  'Portable result contains an absolute local drive path.')
                result = json.loads(data, parse_constant=lambda value: self.fail('Nonfinite JSON: ' + value))
                self.assertEqual(result['source_sha256'], case['source_sha256'])
                self.assertEqual(Path(result['source_path']).name,
                                 case['source_path'].split('/')[-1])
                receipt = json.loads((directory / case['provenance_path']).read_text(encoding='utf-8'))
                self.assertEqual(receipt['specification_sha256'], generator.sha(directory / 'studies.json'))
                self.assertEqual(receipt['case']['result_sha256'], case['result_sha256'])
                normalized = Path(generator.__file__).read_bytes().replace(b'\r\n', b'\n')
                self.assertEqual(receipt['generator_sha256'], hashlib.sha256(normalized).hexdigest())
                if case['kind'] == 'quick-pi':
                    values = result['result']
                    self.assertLess(abs(values['current_balance_error_A']), 1e-8)
                    self.assertLess(abs(values['energy_relative_error']), 1e-6)
                    self.assertGreater(values['voltage_drop_V'], 0)
                    self.assertEqual(len(values['potential_V']), len(result['mesh']['points_mm']))
                elif case['kind'] == 'quick-therm':
                    self.assertEqual(result['pocket_kivi_export']['zBasis'], 'front-depth')
                    balance = result['thermal_network']['heat_balance']
                    self.assertLess(abs(balance['residual_w']), balance['tolerance_w'])
                    self.assertEqual(balance['input_w'], 0.75)
                    self.assertTrue(result['thermal_network']['layers'])
                else:
                    self.assertEqual(result['status'], 'SCREENED')
                    self.assertEqual(result['eye']['status'], 'UNAVAILABLE')
                    self.assertGreater(result['delay_ns'], 0)


if __name__ == '__main__':
    unittest.main()
