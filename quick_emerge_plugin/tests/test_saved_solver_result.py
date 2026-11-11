import gzip
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from quick_emerge_plugin.saved_solver_result import load_solver_json


class SavedSolverIntakeTests(unittest.TestCase):
    def test_real_portable_result_is_read_only_and_source_unverified(self):
        root=Path(__file__).resolve().parents[2]
        path=root/'examples/quick_emerge/research_antennas/images/paper-vnext/cheh-lin-2023-siw-dra/solved-samples.json.gz'
        with mock.patch('quick_emerge_plugin.reporting.source_identity',side_effect=AssertionError('Source was reattached')):
            loaded=load_solver_json(path)
        self.assertEqual(loaded['receipt']['source_state'],'unverified')
        self.assertEqual(loaded['bundle']['source']['path'],'context.kicad_pcb')
        self.assertEqual(loaded['bundle']['research']['id'],'cheh-lin-2023-siw-dra')

    def test_gzip_expansion_is_bounded_before_json_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.json.gz'; path.write_bytes(gzip.compress(b'x'*1000))
            with mock.patch('wayricad_runtime.project_results.MAX_BYTES',32):
                with self.assertRaisesRegex(ValueError,'Expanded'):
                    load_solver_json(path)

    def test_nonfinite_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.json'; path.write_text('{"x":NaN}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Non-finite'):
                load_solver_json(path)
