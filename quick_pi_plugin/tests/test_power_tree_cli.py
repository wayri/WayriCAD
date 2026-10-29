"""Power-intent CLI modes do not silently change a solver or source file."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quick_pi_plugin.cli import main
from quick_pi_plugin.power_tree import empty_tree


class PowerTreeCLITests(unittest.TestCase):
    def test_validate_and_protect_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'tree.json'
            original=json.dumps(empty_tree()).encode();source.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--power-tree',str(source)]),0)
                self.assertEqual(main(['--power-tree',str(source),'--output',str(source)]),2)
                self.assertEqual(main(['--power-tree',str(source),'--current','2']),2)
            self.assertEqual(source.read_bytes(),original)

    def test_output_cannot_overwrite_declared_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.json';source.write_text('retained evidence')
            tree=Path(tmp)/'tree.json';tree.write_text(json.dumps(empty_tree({'source_path':str(source)})))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--power-tree',str(tree),'--output',str(source)]),2)
            self.assertEqual(source.read_text(),'retained evidence')

    def test_infer_records_hash_and_preserves_unreviewed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            board=Path(tmp)/'board.kicad_pcb';board.write_text('(kicad_pcb)')
            inventory={'nets':['+5V'],'terminals':[],'source_sha256':'a'*64}
            stream=io.StringIO()
            with patch('quick_pi_plugin.service.run_job',return_value=inventory),contextlib.redirect_stdout(stream):
                self.assertEqual(main([str(board),'--infer-power-tree']),0)
            result=json.loads(stream.getvalue())
            self.assertEqual(result['source']['source_sha256'],'a'*64)
            self.assertFalse(result['nodes'][0]['reviewed'])


if __name__=='__main__': unittest.main()
