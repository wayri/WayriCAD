from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from manufacturing_readiness_plugin.dfm_cli import main


class FabricationCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = self.root / 'reference.json'
        self.observed = self.root / 'observed.json'
        self.write(self.reference, ['GND', 'GND', 'OUT', 'OUT'])
        self.write(self.observed, ['10', '10', '20', '20'])

    def write(self, path, nets):
        identities = [('U1', '1'), ('J1', '1'), ('U1', '2'), ('J1', '2')]
        value = dict(schema='wayricad.fab-netlist/v1', units='mm',
            terminals=[dict(reference=ref, pin=pin, net=net) for (ref, pin), net in zip(identities, nets)])
        path.write_text(json.dumps(value), encoding='utf-8')

    def run_cli(self, *options):
        output, error = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = main(['fab-compare', '--reference', str(self.reference), '--cam', str(self.observed), *map(str, options)])
        return code, output.getvalue(), error.getvalue()

    def test_renumbered_groups_match_only_after_independent_review(self):
        code, text, error = self.run_cli('--confirm-independent-cam')
        self.assertEqual((code, error), (0, ''))
        report = json.loads(text)
        self.assertEqual(report['status'], 'MATCH')
        self.assertIs(report['fabrication_verified'], False)
        self.assertEqual(self.run_cli()[0], 3)

    def test_one_short_group_exports_complete_evidence(self):
        self.write(self.observed, ['168'] * 4)
        options = []
        for kind, suffix in [('json', 'json'), ('html', 'html'), ('csv', 'csv'), ('text', 'txt')]:
            options.extend(['--' + kind, self.root / ('comparison.' + suffix)])
        code, output, error = self.run_cli(*options)
        self.assertEqual((code, error), (1, ''))
        report = json.loads(output)
        self.assertEqual(report['summary']['short_groups'], 1)
        self.assertEqual(report['shorts'][0]['design_nets'], ['GND', 'OUT'])
        for suffix in ('json', 'html', 'csv', 'txt'):
            exported = (self.root / ('comparison.' + suffix)).read_text(encoding='utf-8')
            self.assertIn('168', exported)
            self.assertIn('GND', exported)

    def test_source_alias_output_is_rejected_without_changes(self):
        before = self.reference.read_bytes()
        code, _, error = self.run_cli('--json', self.reference)
        self.assertEqual(code, 2)
        self.assertIn('overwrite', error)
        self.assertEqual(self.reference.read_bytes(), before)

    def test_self_comparison_never_establishes_independent_match(self):
        self.observed.write_bytes(self.reference.read_bytes())
        code, output, error = self.run_cli('--confirm-independent-cam')
        self.assertEqual((code, error), (3, ''))
        self.assertEqual(json.loads(output)['status'], 'UNKNOWN')

    def test_split_partition_reports_an_open(self):
        self.write(self.observed, ['10', '11', '20', '20'])
        code, output, error = self.run_cli('--confirm-independent-cam')
        self.assertEqual((code, error), (1, ''))
        self.assertEqual(json.loads(output)['summary']['open_groups'], 1)


if __name__ == '__main__':
    unittest.main()
