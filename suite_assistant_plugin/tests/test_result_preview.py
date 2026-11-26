"""Regression checks for the Assistant's static report boundary."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from suite_assistant_plugin import result_preview


class ResultPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name

    def preview(self, filename, data):
        path = Path(self.directory) / filename
        path.write_bytes(data)
        return result_preview.preview_content(path)

    def test_report_keeps_tables_and_discards_active_content(self):
        markup, png, svg = self.preview('report.html', b'''
            <head><base href="https://external.invalid"></head>
            <table><tr><td onmouseover="alert(1)">3.30 V</td></tr></table>
            <script>alert(1)</script><style>body{background:url(https://external.invalid)}</style>
            <iframe src="https://external.invalid">remote</iframe>
            <img src="file:///secret.png"><a href="https://external.invalid">Details</a>
            <p>&lt;img src=file:///secret.png&gt;</p>
        ''')
        self.assertIn('<tr><td>3.30 V</td></tr>', markup)
        self.assertIn('Details', markup)
        self.assertIn('&lt;img', markup)
        for unwanted in ('alert', 'https:', '<img', '<iframe', 'remote'):
            self.assertNotIn(unwanted, markup)
        self.assertIsNone(png)
        self.assertIsNone(svg)

    def test_routing_svg_keeps_primitives_and_removes_references(self):
        _, _, svg = self.preview('preview.svg', b'''
            <svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">
            <polyline points="0,0 25,15 50,15" stroke="#123456" fill="url(https://external.invalid)"/>
            </svg>
        ''')
        self.assertIn(b'points="0,0 25,15 50,15"', svg)
        self.assertIn(b'stroke="#123456"', svg)
        self.assertNotIn(b'url', svg)
        with self.assertRaisesRegex(ValueError, 'drawing features'):
            self.preview('active.svg', b'<svg><image href="file:///secret.png"/></svg>')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            self.preview('doctype.svg', b'<!DOCTYPE svg [<!ENTITY file SYSTEM "file:///secret">]><svg/>')

    def test_nested_results_and_csv_are_tables(self):
        html, _, _ = self.preview('results.json', b'{"cases":[{"net":"VDD","status":"PASS","max_drop_V":0.002}]}')
        self.assertIn('<th>net</th>', html)
        self.assertIn('<td>VDD</td>', html)
        self.assertIn('<td>0.002</td>', html)
        html, _, _ = self.preview('issues.csv', b'Finding,Value\nTrack overlap,0.2\n')
        self.assertIn('<th>Finding</th>', html)
        self.assertIn('<td>Track overlap</td>', html)

    def test_html_draws_a_static_svg_without_preserving_interaction(self):
        html, png, svg = self.preview('ac.html', b'''
            <h1>AC loss</h1><svg viewBox="0 0 100 50" onload="alert(1)">
            <polyline points="0,0 40,20 80,5" stroke="teal"/>
            </svg>
        ''')
        self.assertIn('AC loss', html)
        self.assertIsNone(png)
        self.assertIn(b'viewBox="0 0 100 50"', svg)
        self.assertIn(b'polyline', svg)
        self.assertNotIn(b'onload', svg)

    def test_preview_prefers_solved_s_matrix_over_geometry(self):
        from base64 import b64encode
        from struct import pack
        def sample(width):
            signature = b'\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR'
            return signature + pack('>II', width, 1)
        geometry = b64encode(sample(12)).decode()
        response = b64encode(sample(24)).decode()
        page = (
            f'<img alt="Parametric geometry" src="data:image/png;base64,{geometry}">'
            f'<img alt="S matrix magnitude; solved samples" src="data:image/png;base64,{response}">'
        )
        _, png, _ = self.preview('report.html', page.encode())
        self.assertEqual(png, sample(24))

    def test_compact_json_uses_report_values_and_escapes_text(self):
        html, _, _ = self.preview('report.json', b'{"result":{"voltage_drop_V":0.003,"status":"<pass>"}}')
        self.assertIn('Voltage drop 3 mV', html)
        self.assertIn('&lt;pass&gt;', html)
        self.assertNotIn('voltage_drop_V', html)


if __name__ == '__main__':
    unittest.main()
