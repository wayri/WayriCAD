"""Portable evidence reports preserve values and protect the saved input."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime.report_export import export, html_report
from wayricad_runtime.report_ui import enhance_report


class ReportExportTests(unittest.TestCase):
    def test_all_nested_values_are_escaped_and_unknowns_retained(self):
        result=html_report({'status':'INCOMPLETE','units':[{'net':'<VCC>','delay_ns':None},
            {'net':'GND','voltage_V':0}],'empty':[],'nested':{'limits':[True,False]}})
        for text in ('&lt;VCC&gt;','Unknown / not supplied','Not supplied','voltage V','>0<','>Yes<','>No<'):
            self.assertIn(text,result)
        self.assertNotIn('<VCC>',result)
        self.assertIn('INCOMPLETE',result)

    def test_toc_is_static_unique_and_scripts_not_rewritten(self):
        script='<script>const example="<h2>Not a heading</h2>";</script>'
        html=enhance_report('<h1>Title</h1><h2 id="report-section-1">First</h2><h2>Second</h2>'+script)
        self.assertIn(script,html)
        self.assertIn('href="#report-section-1"',html)
        self.assertIn('href="#report-section-2"',html)
        self.assertNotIn('>Not a heading</a>',html)
        self.assertEqual(enhance_report(html),html)

    def test_raw_arrays_are_optional_while_readable_results_stay_visible(self):
        html=enhance_report('<h1>Review</h1><pre>{"samples": [1, 2, 3]}</pre><pre>Drop: 3.2 mV</pre>')
        self.assertIn('class="report-evidence report-raw-evidence"',html)
        self.assertIn('<summary>Structured evidence (JSON)</summary>',html)
        self.assertIn('<pre>Drop: 3.2 mV</pre>',html)
        self.assertNotIn('<details open',html)

    def test_input_protection_and_atomic_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'input.json';source.write_text('{"load_A":1.5}')
            with self.assertRaises(ValueError):export(source,html=source)
            output=root/'review.html';export(source,html=output)
            self.assertIn('load A',output.read_text(encoding='utf-8'))
            self.assertEqual(json.loads(source.read_text()),{'load_A':1.5})
            with patch('wayricad_runtime.pdf_report.pdf_bytes',side_effect=RuntimeError('missing renderer')):
                with self.assertRaises(RuntimeError):export(source,html=output,pdf=root/'review.pdf')
            self.assertFalse((root/'review.pdf').exists())

    def test_bad_data_is_rejected_without_partial_outputs(self):
        with self.assertRaises(ValueError):html_report({'bad':float('inf')})
        with self.assertRaises(ValueError):html_report(list(range(20001)))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'input.json';source.write_text('{"bad":NaN}')
            with self.assertRaises(ValueError):export(source,html=root/'out.html')
            self.assertFalse((root/'out.html').exists())

    def test_rlc_and_si_board_fingerprint_spelling_is_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);board=root/'board.kicad_pcb';board.write_text('original')
            source=root/'result.json';source.write_text(json.dumps({'board':str(board),'board_sha256':hashlib.sha256(board.read_bytes()).hexdigest()}))
            board.write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'):export(source,html=root/'review.html')
            self.assertFalse((root/'review.html').exists())


if __name__=='__main__':unittest.main()
