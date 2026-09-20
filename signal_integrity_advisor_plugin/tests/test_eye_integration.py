"""End-to-end contracts for the optional SI eye and dependency-free CLI."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from signal_integrity_advisor_plugin.cli import main
from signal_integrity_advisor_plugin.eye_model import simulate_eye
from signal_integrity_advisor_plugin.eye_view import eye_section, standalone_html, plots
from signal_integrity_advisor_plugin.measurement import PathMeasurement
from signal_integrity_advisor_plugin.quick_si import html_report, screen


class EyeIntegrationTests(unittest.TestCase):
    def path(self, **changes):
        fields = dict(status='ok', length_mm=100., impedance_valid=True,
                      impedance_ohm=50., propagation_delay_ns=1.)
        fields.update(changes)
        return PathMeasurement('DATA', 'U1.1', 'J1.1', **fields)

    def eye(self):
        return simulate_eye(z0_ohm=50, delay_ns=1, source_ohm=50,
                            rise_ns=.1, bitrate_mbps=1000)

    def test_standalone_cli_without_native_dependencies(self):
        # Deliberately make both optional native imports unavailable, even if this
        # test itself runs under a KiCad interpreter that normally supplies them.
        script = "import sys; sys.modules['pcbnew']=None; sys.modules['wx']=None; from signal_integrity_advisor_plugin.cli import main; raise SystemExit(main())"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'eye.json'
            html = Path(temp) / 'eye.html'
            result = subprocess.run([sys.executable, '-c', script, 'eye',
                                     '--z0-ohm', '50', '--delay-ns', '1',
                                     '--source-ohm', '50', '--rise-ns', '.1',
                                     '--bitrate-mbps', '1000', '--output', str(output),
                                     '--html', str(html)],
                                    cwd=Path(__file__).resolve().parents[2],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout = json.loads(result.stdout)
            self.assertEqual(stdout, json.loads(output.read_text(encoding='utf-8')))
            self.assertEqual(stdout['status'], 'ILLUSTRATIVE')
            self.assertIn('<svg', html.read_text(encoding='utf-8'))

    def test_cli_invalid_model_returns_actionable_json_without_outputs(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'invalid.json'
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(['eye', '--z0-ohm', '50', '--delay-ns', '1',
                             '--source-ohm', '0', '--rise-ns', '.1',
                             '--bitrate-mbps', '1000', '--output', str(output)])
            self.assertEqual(code, 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('Non-decaying', json.loads(stderr.getvalue())['error'])
            self.assertFalse(output.exists())

    def test_html_is_offline_and_escapes_text(self):
        result = self.eye()
        result['limitations'].append('<script>alert("unsafe")</script>')
        html = standalone_html(result)
        self.assertEqual(html.count('<svg '), 2)
        self.assertNotIn('<script', html)
        self.assertNotIn('src=', html)
        self.assertNotIn('href=', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('not an IBIS simulation or protocol compliance test', html)
        self.assertIn('0.5 UI', html)
        self.assertIn('periodic', html.lower())
        self.assertIn('Thevenin', html)
        unavailable = eye_section({'status': 'UNAVAILABLE', 'reason': '<unsafe>'})
        self.assertIn('&lt;unsafe&gt;', unavailable)

    def test_step_plot_limits_include_transient_not_only_eye_range(self):
        result = self.eye()
        result['step_response']['voltage_v'][20] = 3.0
        step_plot = plots(result)[1]
        self.assertGreater(step_plot[-1][1], 3.0)

    def test_missing_route_information_never_generates_eye(self):
        for path in (self.path(status='disconnected'),
                     self.path(status='partial', impedance_valid=False),
                     self.path(impedance_valid=False),
                     self.path(propagation_delay_ns=0)):
            with self.subTest(path=path):
                report = screen(path, eye_bitrate_mbps=1000)
                self.assertEqual(report['eye']['status'], 'UNAVAILABLE')
                self.assertNotIn('traces_v', report['eye'])

    def test_multi_terminal_or_zone_routes_refuse_uniform_eye(self):
        for path, terminals in ((self.path(), 3), (self.path(), 1),
                                (self.path(zone_count=1), 2)):
            with self.subTest(terminals=terminals, zones=path.zone_count):
                result = screen(path, terminal_count=terminals, eye_bitrate_mbps=1000)
                self.assertEqual(result['eye']['status'], 'UNAVAILABLE')
                self.assertIn('without zones or extra branches', result['eye']['reason'])

    def test_via_path_is_only_illustrative_and_discloses_discontinuities(self):
        result = screen(self.path(via_count=2, layer_changes=2),
                        source_ohm=50, rise_ns=.1, eye_bitrate_mbps=1000)
        self.assertEqual(result['eye']['status'], 'ILLUSTRATIVE')
        self.assertTrue(any('transitions are not calculated' in note for note in result['notes']))
        self.assertTrue(any('vias' in note for note in result['eye']['limitations']))
        html = html_report(result)
        self.assertIn('Illustrative eye', html)
        self.assertIn('transitions are not calculated', html)

    def test_option_off_leaves_original_screen_unchanged(self):
        default = screen(self.path())
        disabled = screen(self.path(), eye_bitrate_mbps=None, eye_swing_v='ignored')
        self.assertEqual(disabled, default)
        self.assertNotIn('eye', default)
        self.assertNotIn('eye_bitrate_mbps', default['inputs'])
        self.assertNotIn('Illustrative eye', html_report(default))


if __name__ == '__main__':
    unittest.main()
