"""Offline report review, source protection and recoverable paired publication."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wayricad_runtime.report_ui import enhance_report, publish_report, publish_documents


class ReportReviewTests(unittest.TestCase):
    def test_untrusted_summary_is_text_and_existing_probes_are_retained(self):
        attack='</script><script>alert("unsafe")</script>'
        html=enhance_report('<!doctype html><h1>Report</h1><h2>Results</h2><script>window.probeRetained=true;</script>',status=attack,summary=[('Net',attack)],notice=attack,provenance={'source_sha256':attack})
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn(attack,html)
        self.assertIn('window.probeRetained=true;',html)
        self.assertIn('report-nav',html)
        self.assertIn('beforeprint',html)
        self.assertNotIn('https://',html)
        self.assertNotIn('http://',html)

    def test_existing_report_replacement_and_exact_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'report.html'
            output.write_text('old html');output.with_suffix('.json').write_text('old evidence')
            paths=publish_report(output,'new html',{'model':'explicit','missing':None})
            self.assertEqual(output.read_text(),'new html')
            self.assertEqual(json.loads(Path(paths['json']).read_text()),{'model':'explicit','missing':None})
            self.assertEqual(sorted(p.name for p in Path(temporary).iterdir()),['report.html','report.json'])

    def test_second_replace_failure_restores_both_previous_files(self):
        import wayricad_runtime.report_ui as module
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'report.html';evidence=output.with_suffix('.json')
            output.write_bytes(b'original html');evidence.write_bytes(b'original evidence')
            replace=module.os.replace;failed=False
            def fail_html_once(source,target):
                nonlocal failed
                if Path(target)==output and not failed:
                    failed=True
                    raise OSError('injected publication error')
                return replace(source,target)
            with patch.object(module.os,'replace',side_effect=fail_html_once):
                with self.assertRaisesRegex(OSError,'publication error'):
                    publish_report(output,'candidate',{'case':1})
            self.assertEqual(output.read_bytes(),b'original html')
            self.assertEqual(evidence.read_bytes(),b'original evidence')
            self.assertEqual(len(list(Path(temporary).iterdir())),2)

    def test_nonfinite_evidence_does_not_touch_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'report.html';output.write_text('original')
            with self.assertRaises(ValueError):publish_report(output,'candidate',{'bad':float('nan')})
            self.assertEqual(output.read_text(),'original')
            self.assertFalse(output.with_suffix('.json').exists())

    def test_source_study_aliases_and_changed_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'board.kicad_pcb';source.write_bytes(b'source')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            output=root/'report.html';evidence=output.with_suffix('.json');evidence.write_text('study')
            with self.assertRaisesRegex(ValueError,'overwrite'):
                publish_report(output,'candidate',{'request':{'study_input_path':str(evidence)}})
            with self.assertRaisesRegex(ValueError,'design'):
                publish_report(source,'candidate',{})
            with self.assertRaisesRegex(ValueError,'changed'):
                publish_report(output,'candidate',{'request':{'board_path':str(source)},'source_sha256':'0'*64})
            self.assertEqual(source.read_bytes(),b'source')
            self.assertFalse(output.exists())
            self.assertEqual(evidence.read_text(),'study')
            publish_report(output,'candidate',{'request':{'board_path':str(source)},'source_sha256':digest})


if __name__=='__main__':unittest.main()
