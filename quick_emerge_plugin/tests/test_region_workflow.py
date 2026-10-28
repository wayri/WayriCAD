"""Default-Python custody checks; mocks never claim native/solver validation."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from quick_emerge_plugin import backend
from quick_emerge_plugin.model import source_identity, validate_config
from quick_emerge_plugin.region_backend import qualification_region, region_digest
from quick_emerge_plugin.session import StudySession


class RegionWorkflowTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / '.tmp'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='region-workflow-', dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.board = self.root / 'coupon.kicad_pcb'
        self.board.write_bytes(b'(kicad_pcb (version 20260101))')
        self.config = validate_config(dict(mode='pcb_region', rule_area_id='qualification-coupon',
            signal_net='SIGNAL', reference_net='GND', region_er_reviewed=True))
        self.region = qualification_region()
        self.region['source'] = source_identity(self.board)
        self.session = StudySession(self.board)

    def preview(self):
        return self.session.preview(self.config, region=self.region)

    def request(self, review):
        path = self.root / 'request.json'
        path.write_text(json.dumps(review), encoding='utf-8')
        return path

    def result(self):
        # Deliberately distinct matrix entries expose partial/reordered export.
        return dict(config=self.config, config_sha256=self.preview()['config_sha256'],
            region_sha256=region_digest(self.region), region=copy.deepcopy(self.region),
            port_count=2, frequencies_hz=[1e9, 2e9],
            s_parameters={name: [[n / 10, -n / 100], [n / 20, n / 100]]
                          for n, name in enumerate(('S11', 'S21', 'S12', 'S22'), 1)})

    def test_preview_binds_exact_source_and_region(self):
        review = self.preview()
        self.assertEqual(review['source'], source_identity(self.board))
        self.assertEqual(review['region_sha256'], region_digest(self.region))
        wrong = copy.deepcopy(self.region)
        wrong['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source'):
            self.session.preview(self.config, region=wrong)
        self.board.write_bytes(b'changed board bytes')
        with self.assertRaisesRegex(ValueError, 'source'):
            self.session.preview(self.config, region=self.region)

    def test_worker_rejects_stale_geometry_before_solve(self):
        review = copy.deepcopy(self.preview())
        # Metadata is also custody protected, independently of valid port shapes.
        review['region']['area']['name'] = 'changed after review'
        with patch.object(backend, 'solve') as solve:
            with self.assertRaisesRegex(ValueError, 'geometry or source'):
                backend.run_request(self.request(review))
            solve.assert_not_called()
        self.assertFalse((self.root / 'result.json').exists())

    def test_worker_rejects_wrong_region_source_before_solve(self):
        review = copy.deepcopy(self.preview())
        review['region']['source']['sha256'] = '0' * 64
        review['region_sha256'] = region_digest(review['region'])
        with patch.object(backend, 'solve') as solve:
            with self.assertRaisesRegex(ValueError, 'geometry or source'):
                backend.run_request(self.request(review))
            solve.assert_not_called()

    def test_worker_rejects_board_modified_after_review(self):
        review = copy.deepcopy(self.preview())
        self.board.write_bytes(b'new board')
        with patch.object(backend, 'solve') as solve:
            with self.assertRaisesRegex(ValueError, 'PCB changed'):
                backend.run_request(self.request(review))
            solve.assert_not_called()

    def test_success_publishes_real_custody_and_full_touchstone(self):
        review = copy.deepcopy(self.preview())
        solved = self.result()
        with patch.object(backend, 'solve', return_value=solved) as solve:
            result = backend.run_request(self.request(review))
        solve.assert_called_once_with(self.config, region=review['region'])
        published = json.loads((self.root / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual(published, result)
        self.assertEqual(published['source'], source_identity(self.board))
        self.assertEqual(published['region_sha256'], region_digest(self.region))
        lines = (self.root / 'network.s2p').read_text().splitlines()
        samples = [list(map(float, line.split())) for line in lines if line and line[0] not in '!#']
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0], [1e9, .1, -.01, .2, -.02, .3, -.03, .4, -.04])
        self.assertEqual(samples[1], [2e9, .05, .01, .1, .02, .15, .03, .2, .04])

    def test_collect_rejects_region_digest_mismatch(self):
        self.preview()
        result = self.result()
        result.update(source=source_identity(self.board), region_sha256='wrong')
        (self.root / 'result.json').write_text(json.dumps(result), encoding='utf-8')
        (self.root / 'status.json').write_text(json.dumps({'status': 'completed'}), encoding='utf-8')
        self.session.run_dir = self.root
        self.session.process = Mock(returncode=0)
        self.session.process.poll.return_value = 0
        self.session.log = io.BytesIO()
        with self.assertRaisesRegex(ValueError, 'rule-area geometry'):
            self.session.collect()

    def test_config_requires_explicit_review_and_nonempty_typed_selection(self):
        bad = [('region_er_reviewed', False), ('region_er_reviewed', 1), ('region_er_reviewed', 'true')]
        bad += [(key, value) for key in ('rule_area_id', 'signal_net', 'reference_net')
                for value in ('', '   ', 123, None)]
        for key, value in bad:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_config(dict(self.config, **{key: value}))

    def test_preview_rejects_wrong_area_or_net_selection(self):
        for key, value in (('rule_area_id', 'different-area'), ('signal_net', 'OTHER'),
                           ('reference_net', 'OTHER')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.session.preview(dict(self.config, **{key: value}), region=self.region)


if __name__ == '__main__':
    unittest.main()
