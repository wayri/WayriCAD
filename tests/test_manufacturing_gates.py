import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from manufacturing_readiness_plugin.analysis import FabricatorProfile,ReadinessCheck,build_release,saved_metrics
from manufacturing_readiness_plugin.verification import capture_inputs,VerificationSnapshot

PCB='(kicad_pcb (general (thickness 1.6)) (layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (segment (width 0.2)) (via (size 0.6) (drill 0.3)))'
PROJECT=json.dumps({'board':{'design_settings':{'rules':{'min_clearance':0.2}}}})
PASS=[ReadinessCheck('PASS','test','1','1')]


class ManufacturingGateTests(unittest.TestCase):
    def files(self,root):
        (root/'board.kicad_pcb').write_text(PCB,encoding='utf-8')
        (root/'board.kicad_pro').write_text(PROJECT,encoding='utf-8')
        (root/'release.kicad_jobset').write_text('{}',encoding='utf-8')

    def test_metrics_read_exact_saved_widths_and_rules(self):
        metrics=saved_metrics(PCB.encode(),PROJECT.encode())
        self.assertEqual(metrics.minimum_track_mm,0.2)
        self.assertEqual(metrics.minimum_annular_ring_mm,0.15)
        self.assertEqual(metrics.copper_layers,2)
        with self.assertRaisesRegex(ValueError,'minimum clearance'):
            saved_metrics(PCB.encode(),b'{}')

    def test_changes_in_each_gate_input_invalidate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.files(root);profile=FabricatorProfile()
            capture=lambda: capture_inputs(root/'board.kicad_pcb',root,profile,root/'release.kicad_jobset',PCB)
            files,key,job=capture();snapshot=VerificationSnapshot(files,key,'board.kicad_pcb',job)
            try:
                snapshot.record('drc',True,{});snapshot.record('jobset',True,{})
                self.assertTrue(snapshot.ready(key))
                profile.minimum_drill_mm=0.25
                with self.assertRaisesRegex(ValueError,'changed'):snapshot.ready(capture()[1])
                profile.minimum_drill_mm=0.20
                (root/'release.kicad_jobset').write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError,'changed'):snapshot.ready(capture()[1])
                with self.assertRaisesRegex(ValueError,'differs'):
                    capture_inputs(root/'board.kicad_pcb',root,profile,'',PCB.replace('0.2','0.1'))
                snapshot.record('drc',True,{})
                with self.assertRaisesRegex(ValueError,'selected jobset'):snapshot.ready(key)
            finally:snapshot.owner.cleanup()

    def test_cli_mutation_of_source_invalidates_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.files(root)
            files,key,job=capture_inputs(root/'board.kicad_pcb',root,FabricatorProfile(),'',PCB)
            snapshot=VerificationSnapshot(files,key,'board.kicad_pcb',job)
            try:
                (snapshot.root/'board.kicad_pro').write_text('{}')
                with self.assertRaisesRegex(ValueError,'modified'):snapshot.record('drc',True,{})
            finally:snapshot.owner.cleanup()

    def test_release_hashes_the_exact_bytes_written_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'board.kicad_pcb';source.write_bytes(b'first')
            original=Path.read_bytes;reads=[]
            def read_once(path):
                result=original(path)
                if path==source:
                    reads.append(path);source.write_bytes(b'changed-after-read')
                return result
            with patch.object(Path,'read_bytes',read_once):
                manifest=build_release(root/'release.zip',[source],PASS,'test')
            self.assertEqual(len(reads),1)
            with zipfile.ZipFile(root/'release.zip') as archive:
                data=archive.read('board.kicad_pcb')
                self.assertEqual(data,b'first')
                self.assertEqual(hashlib.sha256(data).hexdigest(),manifest['files'][0]['sha256'])

    def test_mismatched_hash_does_not_replace_existing_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.write_bytes(b'changed')
            destination=root/'release.zip';destination.write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError,'changed'):
                build_release(destination,[source],PASS,'test',expected_hashes={'source':'wrong'})
            self.assertEqual(destination.read_bytes(),b'existing')
            with self.assertRaisesRegex(ValueError,'completed'):
                build_release(destination,[source],[],'test')


if __name__=='__main__':unittest.main()
