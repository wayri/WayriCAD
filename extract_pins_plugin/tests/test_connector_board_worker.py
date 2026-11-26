"""Saved-board reading stays outside the installed IPC pcbnew facade."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extract_pins_plugin import connector_board_worker as worker

try:
    import pcbnew as native
except ImportError:
    native=None


class WorkerBoundaryTests(unittest.TestCase):
    def test_invalid_source_does_not_probe_a_runtime(self):
        with patch('wayricad_runtime.runtime_setup.native_python') as runtime:
            with self.assertRaises(ValueError):worker.load_inventory('missing-connector.txt')
            runtime.assert_not_called()

    def fixture(self,outcome,code):
        def run(command,**kwargs):
            self.assertEqual(command[1],'-I')
            self.assertTrue(command[2].endswith('connector_board_worker.py'))
            self.assertNotEqual(Path(command[3]).resolve(),Path(command[4]).resolve())
            Path(command[4]).write_text(json.dumps(outcome),encoding='utf-8')
            return SimpleNamespace(returncode=code,stderr='',stdout='')
        return run

    def test_ipc_parent_never_needs_loadboard(self):
        expected={'inventory':{'J2':[dict(pin='1',label='CLK',x_mm=0,y_mm=0)]},'errors':{},'source_sha256':'fixture'}
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_text('saved fixture')
            with patch.dict(sys.modules,{'pcbnew':SimpleNamespace(_wayricad_ipc=True)}), \
                 patch('wayricad_runtime.runtime_setup.native_python',return_value=Path(sys.executable)), \
                 patch('wayricad_runtime.runtime_setup.child_environment',return_value={}), \
                 patch.object(worker.subprocess,'run',side_effect=self.fixture(expected,0)):
                self.assertEqual(worker.load_inventory(source),expected)
            self.assertEqual(source.read_text(),'saved fixture')

    def test_worker_rejection_is_actionable_and_keeps_the_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_text('saved fixture')
            with patch('wayricad_runtime.runtime_setup.native_python',return_value=Path(sys.executable)), \
                 patch('wayricad_runtime.runtime_setup.child_environment',return_value={}), \
                 patch.object(worker.subprocess,'run',side_effect=self.fixture({'error':'duplicate connector reference'},1)):
                with self.assertRaisesRegex(ValueError,'duplicate connector'):worker.load_inventory(source)
            self.assertEqual(source.read_text(),'saved fixture')


@unittest.skipIf(native is None,'Native KiCad saved-board reader required')
class NativeWorkerTests(unittest.TestCase):
    def test_duplicate_pad_numbers_keep_distinct_preview_uuids(self):
        from extract_pins_plugin.core.data_extractor import DataExtractor
        board = native.BOARD()
        footprint = native.FOOTPRINT(board)
        footprint.SetReference('J1')
        board.Add(footprint)
        expected = set()
        for x in (0, 1000000):
            pad = native.PAD(footprint)
            pad.SetNumber('1')
            pad.SetPosition(native.VECTOR2I(x, 0))
            footprint.Add(pad)
            expected.add(pad.m_Uuid.AsString())
        extractor = DataExtractor(board)
        pins = extractor.extract_footprint_data([footprint], include_pad_uuids=True)['J1']['pins']
        self.assertEqual([p['Pad Name/Number'] for p in pins], ['1', '1'])
        self.assertEqual({p['pad_uuid'] for p in pins}, expected)
        self.assertEqual(len(expected), 2)
        self.assertTrue(all('pad_uuid' not in p for p in extractor.extract_footprint_data([footprint])['J1']['pins']))

    def test_real_native_child_works_with_an_ipc_only_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'connector.kicad_pcb';board=native.BOARD()
            fp=native.FOOTPRINT(board);fp.SetReference('J2');board.Add(fp)
            net=native.NETINFO_ITEM(board,'CLK');board.Add(net)
            pad=native.PAD(fp);pad.SetNumber('1');pad.SetPosition(native.VECTOR2I(1000000,2000000));pad.SetNet(net);fp.Add(pad)
            native.SaveBoard(str(source),board);before=hashlib.sha256(source.read_bytes()).hexdigest()
            with patch.dict(sys.modules,{'pcbnew':SimpleNamespace(_wayricad_ipc=True)}):
                result=worker.load_inventory(source)
            self.assertEqual(result['source_sha256'],before)
            self.assertEqual(result['inventory']['J2'],[dict(pin='1',label='CLK',x_mm=1.,y_mm=2.)])
            self.assertFalse(result['errors'])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)


if __name__=='__main__':unittest.main()
