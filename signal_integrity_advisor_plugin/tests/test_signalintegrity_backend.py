"""Analytical two-port checks and strict optional upstream adapter contracts."""
import cmath
import contextlib
import io
import json
import math
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signal_integrity_advisor_plugin.cli import main
from signal_integrity_advisor_plugin.signalintegrity_backend import analyze_touchstone, ideal_line_touchstone, run_desktop


def route(**changes):
    result = dict(schema='wayricad.quick-si/v1', status='SCREENED', terminal_count=2,
                  path={'zone_count': 0}, z0_ohm=50., delay_ns=1.)
    result.update(changes)
    return result


def records(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith(('!', '#')):
            values = list(map(float, line.split()))
            rows.append((values[0], [complex(*values[i:i+2]) for i in range(1, 9, 2)]))
    return rows


class IdealLineTests(unittest.TestCase):
    def test_matched_line_matches_analytical_delay(self):
        for frequency, (s11, s21, s12, s22) in records(ideal_line_touchstone(route(), stop_hz=1e9, points=5)):
            self.assertAlmostEqual(abs(s11), 0.)
            self.assertAlmostEqual(abs(s22), 0.)
            self.assertAlmostEqual(abs(s21 - cmath.exp(-2j * math.pi * frequency * 1e-9)), 0.)
            self.assertEqual(s21, s12)

    def test_mismatched_line_conserves_power_and_quarter_wave_reference(self):
        rows = records(ideal_line_touchstone(route(z0_ohm=100), stop_hz=1e9, points=17))
        for _, (s11, s21, s12, s22) in rows:
            self.assertAlmostEqual(abs(s11)**2 + abs(s21)**2, 1.)
            self.assertEqual(s12, s21)
            self.assertEqual(s22, s11)
        self.assertAlmostEqual(rows[4][1][0].real, .6)
        self.assertAlmostEqual(rows[4][1][1].imag, -.8)

    def test_unknown_and_unsupported_routes_stay_unknown(self):
        for change in ({'status':'INCOMPLETE'}, {'z0_ohm':None}, {'delay_ns':float('nan')},
                       {'terminal_count':3}, {'path':{'zone_count':1}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ideal_line_touchstone(route(**change), stop_hz=1e9)
        for points in (1, 10002, 3.2, True):
            with self.assertRaises(ValueError):
                ideal_line_touchstone(route(), stop_hz=1e9, points=points)

    def test_cli_exports_without_optional_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'route.json'
            target = Path(folder)/'channel.s2p'
            source.write_text(json.dumps(route()), encoding='utf-8')
            with patch.dict('sys.modules', {'SignalIntegrity':None}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['line-network', str(source), '--stop-hz', '1e9', '--points', '5', '--output', str(target)]), 0)
            self.assertIn('NOT EXTRACTED BOARD', target.read_text())
            self.assertEqual(len(records(target.read_text())), 5)


class TouchstoneValidationTests(unittest.TestCase):
    def analyze(self, text, **options):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'network.s2p'
            source.write_text(text, encoding='utf-8')
            return analyze_touchstone(source, **options)

    def test_rejects_truncated_nonfinite_duplicate_and_non_s_data(self):
        for text in ('# Hz S RI R 50\n0 0 0\n', '# Hz S RI R 50\n0 nan 0 1 0 1 0 0 0\n',
                     '# Hz Y RI R 50\n0 0 0 1 0 1 0 0 0\n',
                     '# Hz S RI R 50\n0 0 0 1 0 1 0 0 0\n0 0 0 1 0 1 0 0 0\n',
                     '[Version] 2.0\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.analyze(text)

    def test_missing_backend_is_actionable(self):
        with patch.dict('sys.modules', {'SignalIntegrity.Lib.SParameters.SParameterFile':None}):
            with self.assertRaisesRegex(RuntimeError, 'Install SignalIntegrity==1.5.2'):
                self.analyze('# Hz S RI R 50\n0 0 0 1 0 1 0 0 0\n')

    def test_port_bounds_checked_before_import(self):
        with self.assertRaisesRegex(ValueError, 'between 1 and 2'):
            self.analyze('# Hz S RI R 50\n0 0 0 1 0 1 0 0 0\n', to_port=3)


class DesktopLaunchTests(unittest.TestCase):
    def probe(self, returncode=0):
        return subprocess.CompletedProcess([], returncode, '{"version":"1.5.2"}\n', 'missing Tk' if returncode else '')

    def test_check_does_not_launch_a_window(self):
        with patch('signal_integrity_advisor_plugin.signalintegrity_backend.subprocess.run', return_value=self.probe()) as runner:
            report = run_desktop(check=True)
            self.assertEqual(report['status'], 'DEPENDENCIES_AVAILABLE')
            self.assertEqual(runner.call_count, 1)

    def test_explicit_project_launch_uses_arguments_without_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)/'project with spaces.si'
            project.write_text('test fixture', encoding='utf-8')
            with patch('signal_integrity_advisor_plugin.signalintegrity_backend.subprocess.run', side_effect=[self.probe(), self.probe()]) as runner:
                report = run_desktop(project=project)
                self.assertEqual(report['status'], 'CLOSED')
                self.assertEqual(runner.call_args.args[0], [str(Path(sys.executable).resolve()), '-m',
                                 'SignalIntegrity.App.SignalIntegrityApp', str(project.resolve())])
                self.assertNotIn('shell', runner.call_args.kwargs)

    def test_dependency_and_launch_failures_are_not_success(self):
        with patch('signal_integrity_advisor_plugin.signalintegrity_backend.subprocess.run', return_value=self.probe(1)):
            with self.assertRaisesRegex(RuntimeError, 'missing Tk'):
                run_desktop(check=True)
        with patch('signal_integrity_advisor_plugin.signalintegrity_backend.subprocess.run', side_effect=[self.probe(), self.probe(7)]):
            with self.assertRaisesRegex(RuntimeError, 'code 7'):
                run_desktop()


class UpstreamIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import SignalIntegrity.Lib
        except ImportError:
            raise unittest.SkipTest('Optional SignalIntegrity numerical runtime is not installed.')

    def test_actual_backend_reads_export_and_keeps_zero_unknown_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'line.s2p'
            source.write_text(ideal_line_touchstone(route(), stop_hz=1e9, points=5), encoding='utf-8')
            transmitted = analyze_touchstone(source)
            reflected = analyze_touchstone(source, to_port=1)
            self.assertEqual(transmitted['frequency_hz'], [0., 250e6, 500e6, 750e6, 1e9])
            for value in transmitted['magnitude_db']:
                self.assertAlmostEqual(value, 0.)
            self.assertAlmostEqual(transmitted['response_imag'][1], -1.)
            self.assertEqual(reflected['magnitude_db'], [None]*5)
            self.assertEqual(reflected['phase_deg'], [None]*5)
            self.assertEqual(transmitted['reference_ohm'], 50.)
            self.assertEqual(len(transmitted['source_sha256']), 64)

    def test_asymmetric_port_order_and_nondefault_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'asymmetric.s2p'
            source.write_text('# GHz S MA R 75\n1 0 0 .5 90 .2 -90 0 0\n', encoding='utf-8')
            forward = analyze_touchstone(source)
            reverse = analyze_touchstone(source, to_port=1, from_port=2)
            self.assertEqual(forward['reference_ohm'], 75.)
            self.assertEqual(forward['frequency_hz'], [1e9])
            self.assertAlmostEqual(forward['response_imag'][0], .5)
            self.assertAlmostEqual(reverse['response_imag'][0], -.2)


if __name__ == '__main__':
    unittest.main()
