import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from embed_3d_plugin.__main__ import main
from embed_3d_plugin.cli_validation import validate_schematic
from test_symbols import schematic

class PortabilityCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'circuit.kicad_sch';self.source.write_text(schematic());self.assets=self.root/'assets'
    def tearDown(self):self.tmp.cleanup()
    def run_cli(self,*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):code=main(list(map(str,args)))
        return code,stream.getvalue()
    def test_extract_dry_run(self):
        code,text=self.run_cli('extract-symbols',self.source,'--output',self.assets,'--json')
        self.assertEqual(code,0);self.assertFalse(json.loads(text)['applied']);self.assertFalse(self.assets.exists())
    def test_extract_then_relink_apply(self):
        code,text=self.run_cli('extract-symbols',self.source,'--output',self.assets,'--apply')
        self.assertEqual(code,0,text);out=self.root/'out'
        code,text=self.run_cli('relink-symbols',self.source,'--assets',self.assets,'--output',out,'--apply','--json')
        self.assertEqual(code,0,text);self.assertTrue((out/self.source.name).is_file());self.assertTrue(json.loads(text)['applied'])
    def test_embed_dry_run_and_apply(self):
        out=self.root/'out';code,text=self.run_cli('embed-symbols',self.source,'--output',out,'--local-links')
        self.assertEqual(code,0,text);self.assertFalse(out.exists())
        code,text=self.run_cli('embed-symbols',self.source,'--output',out,'--local-links','--apply')
        self.assertEqual(code,0,text);self.assertTrue((out/'EmbeddedSymbols.kicad_sym').is_file())
    def test_output_required(self):
        code,_=self.run_cli('extract-symbols',self.source);self.assertEqual(code,2)
    def test_assets_required_for_relink(self):
        code,_=self.run_cli('relink-symbols',self.source,'--output',self.root/'out');self.assertEqual(code,2)
    def test_variable_syntax_guard(self):
        code,_=self.run_cli('extract-symbols',self.source,'--output',self.assets,'--var','broken');self.assertEqual(code,2)
    def test_optional_native_validator_missing_is_error(self):
        with patch('embed_3d_plugin.cli_validation.find_cli',return_value=None),self.assertRaises(ValueError):validate_schematic(self.source)
    def test_wrong_major_cli_rejected(self):
        import subprocess
        with patch('embed_3d_plugin.cli_validation.subprocess.run',return_value=subprocess.CompletedProcess([],0,'9.0.0','')):
            with self.assertRaisesRegex(ValueError,'KiCad 10'):validate_schematic(self.source,'some-cli')
    def test_native_cli_fail_does_not_publish(self):
        out=self.root/'out'
        with patch('embed_3d_plugin.cli_validation.validate_schematic',side_effect=ValueError('rejected')):
            code,_=self.run_cli('embed-symbols',self.source,'--output',out,'--apply','--validate-cli')
        self.assertEqual(code,2);self.assertFalse(out.exists())
