"""Static PDF report semantics, layout bounds and source preservation."""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime.pdf_report import export_pdf, pdf_bytes, main


_PDF = all(importlib.util.find_spec(name) for name in ('reportlab', 'pypdf', 'PIL'))


@unittest.skipUnless(_PDF, 'Optional PDF report/test dependencies are not installed.')
class PdfReportTests(unittest.TestCase):
    def text(self, data):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return '\n'.join(page.extract_text() for page in reader.pages), reader

    def test_exact_values_units_untrusted_markup_and_omissions(self):
        document = '''<!doctype html><html><head><style>CSS_SECRET</style><script>SCRIPT_SECRET</script></head>
        <body><h1>PI &amp; thermal evidence</h1><p>R&lt;2 &amp; C&gt;1; 3.293 V; 29.597 µV; 0.03 Ω</p>
        <nav>NAV_SECRET</nav><button>BUTTON_SECRET</button><canvas id="current-map"></canvas>
        <svg aria-label="thermal-surface"><text>SVG_SECRET</text></svg>
        <img src="https://invalid.example/private.png" alt="Remote board"/>
        <table><tr><th>Reference</th><th>Status</th></tr><tr><td>R&lt;2</td><td>Unknown</td></tr></table></body></html>'''
        text, reader = self.text(pdf_bytes(document))
        self.assertIn('29.597 µV', text)
        self.assertIn('0.03 Ω', text)
        self.assertIn('R<2', text)
        self.assertIn('Unknown', text)
        self.assertIn('CANVAS: current-map', text)
        self.assertIn('SVG: thermal-surface', text)
        self.assertIn('External or unsupported image: Remote board', text)
        for secret in ('CSS_SECRET', 'SCRIPT_SECRET', 'SVG_SECRET', 'BUTTON_SECRET', 'NAV_SECRET'):
            self.assertNotIn(secret, text)
        self.assertNotIn('/OpenAction', reader.trailer['/Root'])
        self.assertFalse(any(page.get('/Annots') for page in reader.pages))

    def test_long_and_wide_tables_keep_every_cell_and_repeat_headers(self):
        headers = ['Reference'] + ['Metric ' + str(index) for index in range(1, 9)]
        rows = ['<tr>' + ''.join('<th>' + item + '</th>' for item in headers) + '</tr>']
        for index in range(100):
            rows.append('<tr><td>R' + str(index) + '</td>' + ''.join('<td>' + str(index) + ':' + str(column) + '</td>' for column in range(1, 9)) + '</tr>')
        text, reader = self.text(pdf_bytes('<h1>Long table</h1><table>' + ''.join(rows) + '</table>'))
        self.assertGreater(len(reader.pages), 3)
        self.assertGreater(text.count('Reference'), 3)
        self.assertIn('panel 2 of 2', text)
        for index in range(100):
            for column in range(1, 9):
                self.assertIn(str(index) + ':' + str(column), text)

    def test_embedded_raster_and_long_hash_do_not_clip_or_fetch(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (120, 80), '#087f98').save(buffer, format='PNG')
        image = base64.b64encode(buffer.getvalue()).decode('ascii')
        text, reader = self.text(pdf_bytes('<h1>Board figure</h1><img alt="Embedded board" src="data:image/png;base64,' + image + '"><pre>' + 'a' * 256 + '</pre>'))
        self.assertIn('Embedded board', text)
        resources = reader.pages[0]['/Resources']
        self.assertTrue(resources.get('/XObject'))
        self.assertIn('a' * 256, re.sub(r'\s+', '', text))

    def test_invalid_image_table_and_complexity_fail_without_outputs(self):
        with self.assertRaisesRegex(ValueError, 'Invalid embedded'):
            pdf_bytes('<img src="data:image/png;base64,YmFk">')
        with self.assertRaisesRegex(ValueError, 'column span'):
            pdf_bytes('<table><tr><td colspan="1000">bad</td></tr></table>')
        with self.assertRaisesRegex(ValueError, 'complexity'):
            pdf_bytes('<div>' * 270 + 'deep' + '</div>' * 270)
        with patch('wayricad_runtime.pdf_report.MAX_HTML_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'input limit'):
                pdf_bytes('12345')

    def test_export_preserves_html_evidence_and_design_and_checks_staleness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'report.html'; source.write_text('<h1>Saved report</h1>', encoding='utf-8')
            board = root / 'board.kicad_pcb'; board.write_bytes(b'original board')
            evidence = root / 'report.json'
            payload = {'board_path': str(board), 'source_sha256': hashlib.sha256(board.read_bytes()).hexdigest()}
            evidence.write_text(json.dumps(payload), encoding='utf-8')
            output = root / 'report.pdf'
            export_pdf(source, output, evidence=evidence)
            self.assertTrue(output.read_bytes().startswith(b'%PDF-'))
            self.assertEqual(source.read_text(), '<h1>Saved report</h1>')
            self.assertEqual(board.read_bytes(), b'original board')
            retained = output.read_bytes()
            board.write_bytes(b'changed board')
            with self.assertRaisesRegex(ValueError, 'changed'):
                export_pdf(source, output, evidence=evidence)
            self.assertEqual(output.read_bytes(), retained)
            with self.assertRaisesRegex(ValueError, '.pdf'):
                export_pdf(source, board)
            with self.assertRaisesRegex(ValueError, 'HTML'):
                export_pdf(board, output)

    def test_alias_and_render_failure_keep_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'report.html'; source.write_text('<h1>Saved</h1>')
            output = root / 'report.pdf'; output.write_bytes(b'previous')
            with patch('wayricad_runtime.pdf_report.pdf_bytes', side_effect=ValueError('bad rendering')):
                with self.assertRaisesRegex(ValueError, 'bad rendering'):
                    export_pdf(source, output)
            self.assertEqual(output.read_bytes(), b'previous')
            output.unlink()
            try:
                output.hardlink_to(source)
            except OSError:
                self.skipTest('Filesystem does not permit test hardlinks.')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                export_pdf(source, output)
            self.assertEqual(source.read_text(), '<h1>Saved</h1>')

    def test_report_and_evidence_changes_during_render_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'report.html'; source.write_text('<h1>Saved</h1>')
            evidence = root / 'report.json'; evidence.write_text('{}')
            output = root / 'report.pdf'; output.write_bytes(b'previous')
            def changed_html(*args, **kwargs):
                source.write_text('<h1>Changed</h1>')
                return b'%PDF-candidate'
            with patch('wayricad_runtime.pdf_report.pdf_bytes', side_effect=changed_html):
                with self.assertRaisesRegex(ValueError, 'HTML report changed'):
                    export_pdf(source, output)
            def changed_evidence(*args, **kwargs):
                evidence.write_text('{"status":"changed"}')
                return b'%PDF-candidate'
            with patch('wayricad_runtime.pdf_report.pdf_bytes', side_effect=changed_evidence):
                with self.assertRaisesRegex(ValueError, 'evidence changed'):
                    export_pdf(source, output, evidence=evidence)
            self.assertEqual(output.read_bytes(), b'previous')

    def test_rowspan_and_colspan_keep_merged_text_once(self):
        text, _ = self.text(pdf_bytes('<h1>Merged table</h1><table>'
            '<tr><th>Reference</th><th colspan="2">Grouped metrics</th></tr>'
            '<tr><td rowspan="2">R1</td><td>1.5 V</td><td>2.5 V</td></tr>'
            '<tr><td>3.5 V</td><td>4.5 V</td></tr></table>'))
        self.assertEqual(text.count('R1'), 1)
        for value in ('1.5 V', '2.5 V', '3.5 V', '4.5 V', 'Merged HTML table cells are flattened'):
            self.assertIn(value, text)

    def test_long_json_is_fingerprinted_and_opt_in_restores_exact_appendix(self):
        content = json.dumps({'rows': [{'net': 'DETAILED_NET_' + str(index), 'delay_ns': index / 10} for index in range(120)]}, indent=2)
        html = '<h1>Appendix handling</h1><pre>' + content + '</pre><pre>Small evidence: 29.597 µV</pre>'
        text, reader = self.text(pdf_bytes(html))
        self.assertIn('Small evidence: 29.597 µV', text)
        self.assertIn('Raw JSON evidence retained', text)
        self.assertIn(hashlib.sha256(content.encode('utf-8')).hexdigest(), re.sub(r'\s+', '', text))
        self.assertNotIn('DETAILED_NET_119', text)
        full, full_reader = self.text(pdf_bytes(html, include_raw_evidence=True))
        self.assertIn('DETAILED_NET_119', full)
        self.assertIn('11.9', full)
        self.assertGreater(len(full_reader.pages), len(reader.pages))

    def test_long_non_json_pre_is_never_summarized(self):
        content = 'Important narrative evidence\n' * 160 + 'END_OF_EVIDENCE'
        text, _ = self.text(pdf_bytes('<h1>Narrative</h1><pre>' + content + '</pre>'))
        self.assertIn('END_OF_EVIDENCE', text)
        self.assertNotIn('Raw JSON evidence retained', text)

    def test_small_json_is_also_summarized_by_default(self):
        content = '{"private_detail":"RAW_ONLY_MARKER"}'
        html = '<h1>Summary</h1><pre>' + content + '</pre><pre>Small narrative stays visible</pre>'
        text, _ = self.text(pdf_bytes(html))
        self.assertNotIn('RAW_ONLY_MARKER', text)
        self.assertIn('Raw JSON evidence retained', text)
        self.assertIn('Small narrative stays visible', text)
        raw, _ = self.text(pdf_bytes(html, include_raw_evidence=True))
        self.assertIn('RAW_ONLY_MARKER', raw)

    def test_missing_optional_dependency_is_actionable(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name.startswith('reportlab'):
                raise ImportError('simulated absent optional dependency')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, r'wayricad\[reports\]'):
                pdf_bytes('<h1>Report</h1>')

    def test_cli_reports_real_output_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'report.html'; source.write_text('<h1>CLI</h1>')
            with patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(main([str(source), '--output', str(root / 'report.pdf')]), 0)
                self.assertEqual(json.loads(stdout.getvalue())['pdf'], str(root / 'report.pdf'))
            with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                self.assertEqual(main([str(source), '--output', str(root / 'board.kicad_pcb')]), 2)
                self.assertEqual(json.loads(stderr.getvalue())['status'], 'ERROR')


if __name__ == '__main__':
    unittest.main()
