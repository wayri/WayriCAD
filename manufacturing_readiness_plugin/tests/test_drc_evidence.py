import json
from pathlib import Path
import tempfile
import unittest
from manufacturing_readiness_plugin.verification import drc_evidence


class DrcEvidenceTests(unittest.TestCase):
    def read(self,payload,code):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'drc.json';path.write_text(json.dumps(payload),encoding='utf-8')
            return drc_evidence(path,code)

    def test_violation_exit_preserves_findings(self):
        result=self.read({'violations':[{'type':'clearance'}],'unconnected_items':[]},5)
        self.assertFalse(result['clean'])
        self.assertEqual(result['findings']['violations'],1)
        self.assertEqual(result['types'],{'clearance':1})

    def test_clean_requires_success_and_no_findings(self):
        report={'violations':[],'unconnected_items':[]}
        self.assertTrue(self.read(report,0)['clean'])
        self.assertFalse(self.read(report,5)['clean'])
        self.assertFalse(self.read(dict(report,schematic_parity=[{'type':'mismatch'}]),0)['clean'])

    def test_malformed_native_evidence_is_rejected(self):
        for report in ({},[],{'violations':[1],'unconnected_items':[]},
                       {'violations':[],'unconnected_items':[],'schematic_parity':{}}):
            with self.subTest(report=report),self.assertRaises(ValueError):self.read(report,0)


if __name__=='__main__':unittest.main()
