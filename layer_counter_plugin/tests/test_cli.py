"""CLI candidate exports preserve source and reject destructive destinations."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
try:
    import pcbnew as api
except ImportError:
    api=None
from layer_counter_plugin.cli import main
from layer_counter_plugin import core


@unittest.skipIf(api is None,'Native KiCad bindings required')
class CLITests(unittest.TestCase):
    def test_default_midline_modes_and_saved_inner_copper_mirroring(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.kicad_pcb';b=api.BOARD();b.SetCopperLayerCount(4);api.SaveBoard(str(source),b)
            before=source.read_bytes()
            for options,expected in [([],[False,False,True,True]),(['--mirror-mode','bottom-only'],[False,False,False,True]),
                                     (['--no-mirror'],[False]*4),(['--mirror-mode','core-faces'],[False,True,False,True])]:
                stream=io.StringIO()
                with contextlib.redirect_stdout(stream):self.assertEqual(main([str(source)]+options),0)
                report=json.loads(stream.getvalue());self.assertEqual([r['mirror'] for r in report['labels']],expected)
                self.assertEqual(source.read_bytes(),before)
            candidate=source.with_name('inner-candidate.kicad_pcb')
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main([str(source),'--layers','L2,L3','--output',str(candidate)]),0)
            saved=api.LoadBoard(str(candidate));texts={text.GetText():text for text in saved.GetDrawings() if isinstance(text,api.PCB_TEXT)}
            self.assertFalse(texts['L2'].IsMirrored());self.assertTrue(texts['L3'].IsMirrored())
            for options in (['--no-mirror-bottom','--mirror-mode','lower-half'],['--no-mirror','--mirror-mode','bottom-only']):
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main([str(source)]+options)

    def test_preview_export_companions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.kicad_pcb';output=root/'candidate.kicad_pcb'
            b=api.BOARD();b.SetCopperLayerCount(4);api.SaveBoard(str(source),b)
            original=source.read_bytes()
            source.with_suffix('.kicad_pro').write_text('{"example":"preserved"}',encoding='utf-8')
            source.with_suffix('.kicad_dru').write_text('(version 1)',encoding='utf-8')
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(main([str(source),'--layers','L2,L4']),0)
            report=json.loads(stream.getvalue());self.assertFalse(report['applied'])
            self.assertEqual([row['text'] for row in report['labels']],['L2','L4'])
            self.assertEqual(source.read_bytes(),original);self.assertFalse(output.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(source),'--layers','L2,L4','--output',str(output)]),0)
            self.assertEqual(source.read_bytes(),original)
            loaded=api.LoadBoard(str(output))
            self.assertEqual(sorted(t.GetText() for t in loaded.GetDrawings()),['L2','L4'])
            self.assertEqual(len(list(loaded.Groups())),1)
            self.assertEqual(output.with_suffix('.kicad_pro').read_bytes(),source.with_suffix('.kicad_pro').read_bytes())
            self.assertEqual(output.with_suffix('.kicad_dru').read_bytes(),source.with_suffix('.kicad_dru').read_bytes())
            candidate=output.read_bytes()
            for destination in (source,output):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:main([str(source),'--output',str(destination)])
                self.assertEqual(error.exception.code,2)
                self.assertEqual(output.read_bytes(),candidate)
                self.assertEqual(source.read_bytes(),original)

    def test_invalid_physical_layer_and_pairs_produce_no_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.kicad_pcb';output=source.with_name('candidate.kicad_pcb')
            api.SaveBoard(str(source),api.BOARD())
            for options in (['--layers','L3'],['--layers','L1,L1'],['--style','core-overlap','--core-pairs','L1/L3']):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):main([str(source),'--output',str(output)]+options)
                self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
