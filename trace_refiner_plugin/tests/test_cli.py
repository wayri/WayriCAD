"""Exercise real CLI custody, scoping, validated exports and failure gates."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_native


class HelpTests(unittest.TestCase):
    def test_help_without_native_runtime(self):
        result = subprocess.run([sys.executable, '-m', 'trace_refiner_plugin', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--output', result.stdout)
        self.assertIn('--track', result.stdout)
        self.assertIn('--center-contacts', result.stdout)


@unittest.skipIf(test_native.api is None, 'KiCad native Python required')
class CLITests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_native.NativeTests()
        self.fixture.setUp()
        self.source = self.fixture.path
        self.hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in self.source.parent.iterdir() if p.is_file()}

    def tearDown(self):
        for path, digest in self.hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.fixture.tearDown()

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, '-m', 'trace_refiner_plugin', str(self.source), *args],
                                capture_output=True, text=True, timeout=120)
        payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        return result, payload

    def test_export_validates_and_preserves_source_project(self):
        output = self.source.with_name('refined.kicad_pcb')
        report = self.source.with_name('review.json')
        result, payload = self.run_cli('--net', 'SIGNAL', '--layer', 'F.Cu',
                                       '--output', str(output), '--report', str(report))
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload['status'], 'EXPORTED')
        self.assertEqual(payload['evidence']['new_findings'], 0)
        self.assertEqual(len(payload['changes']), 1)
        self.assertEqual(json.loads(report.read_text()), payload)
        self.assertEqual(output.with_suffix('.kicad_pro').read_bytes(), self.source.with_suffix('.kicad_pro').read_bytes())
        board = test_native.api.LoadBoard(str(output))
        tracks = list(board.GetTracks())
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].GetNetname(), 'SIGNAL')
        before = output.read_bytes()
        result, payload = self.run_cli('--output', str(output))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exist', payload['error'])
        self.assertEqual(output.read_bytes(), before)

    def test_contact_centering_cli_export_and_invalid_shift(self):
        api=test_native.api
        self.fixture.tracks[0].SetStart(self.fixture.v(1.1,2))
        api.SaveBoard(str(self.source),self.fixture.board)
        self.hashes[self.source]=hashlib.sha256(self.source.read_bytes()).hexdigest()
        output=self.source.with_name('centered.kicad_pcb')
        result,payload=self.run_cli('--center-contacts','--max-center-shift','.2','--output',str(output))
        self.assertEqual(result.returncode,0,payload)
        self.assertEqual(payload['settings']['mode'],'center contacts')
        self.assertEqual(len(payload['changes']),1)
        self.assertEqual(payload['evidence']['new_findings'],0)
        self.assertEqual(payload['changes'][0]['after_mm'][0],[1.,2.])
        for value in ('nan','0','2.1'):
            result,payload=self.run_cli('--center-contacts','--max-center-shift',value)
            self.assertNotEqual(result.returncode,0,payload)

    def test_scope_and_invalid_inputs(self):
        result, payload = self.run_cli('--netclass', 'Default')
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload['status'], 'PREVIEW')
        self.assertEqual(len(payload['changes']), 1)
        ids = payload['changes'][0]['track_ids']
        arguments = [item for identity in ids for item in ('--track', identity)]
        result, payload = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(len(payload['changes']), 1)
        for args in (('--net', 'MISSING'), ('--net', 'SIGN*'), ('--layer', 'In99.Cu'),
                     ('--track', 'bad-uuid'), ('--max-deviation', 'nan')):
            with self.subTest(args=args):
                result, payload = self.run_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(payload['status'], 'ERROR')
        result, payload = self.run_cli('--protected', 'SIGN*')
        self.assertEqual(result.returncode, 0, payload)
        self.assertEqual(payload['changes'], [])

    def test_missing_project_blocks_output(self):
        project = self.source.with_suffix('.kicad_pro')
        original = project.read_bytes()
        project.unlink()
        try:
            output = self.source.with_name('blocked.kicad_pcb')
            result, payload = self.run_cli('--output', str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('matching .kicad_pro', payload['error'])
            self.assertFalse(output.exists())
        finally:
            project.write_bytes(original)

    def test_native_clearance_failure_does_not_export(self):
        api = test_native.api
        other = api.NETINFO_ITEM(self.fixture.board, 'OBSTACLE', 2)
        self.fixture.board.Add(other)
        obstacle = self.fixture.track((4, 1.70), (4.5, 1.70))
        obstacle.SetNet(other)
        project = self.source.with_suffix('.kicad_pro')
        project.write_text(json.dumps({'board': {'design_settings': {'rules': {'min_clearance': .12}}}}))
        api.SaveBoard(str(self.source), self.fixture.board)
        self.hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.source, project)}
        output = self.source.with_name('unsafe.kicad_pcb')
        result, payload = self.run_cli('--net', 'SIGNAL', '--output', str(output))
        self.assertNotEqual(result.returncode, 0, payload)
        self.assertRegex(payload['error'], 'DRC|findings')
        self.assertFalse(output.exists())
        self.assertFalse(output.with_suffix('.kicad_pro').exists())


if __name__ == '__main__':
    unittest.main()
