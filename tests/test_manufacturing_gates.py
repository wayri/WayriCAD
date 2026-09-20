import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from manufacturing_readiness_plugin.analysis import FabricatorProfile,ReadinessCheck,audit_metrics,build_release,saved_metrics
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

    def test_custom_anchor_and_uniform_per_layer_padstack_are_bounded(self):
        pads='''
        (footprint "test"
          (pad "1" thru_hole custom (size 1 1) (drill 0.6)
            (layers "*.Cu") (options (clearance outline) (anchor circle))
            (primitives (gr_poly (pts (xy -2 -2) (xy 2 -2) (xy 2 2)) (width 0) (fill yes))))
          (pad "2" thru_hole circle (size 0.8 0.8) (drill 0.4) (layers "*.Cu")
            (padstack (mode front_inner_back)
              (layer "Inner" (shape circle) (size 0.7 0.7))
              (layer "B.Cu" (shape circle) (size 0.6 0.6)))))'''
        board=PCB.replace('(via (size 0.6) (drill 0.3))','')[:-1]+pads+')'
        metrics=saved_metrics(board.encode(),PROJECT.encode())
        self.assertAlmostEqual(metrics.minimum_annular_ring_mm,0.1)

    def test_custom_anchor_lower_bound_cannot_prove_failure(self):
        pad='''(footprint "test" (pad "1" thru_hole custom (size 1 1) (drill 0.9)
          (layers "*.Cu") (options (clearance outline) (anchor circle))
          (primitives (gr_circle (center 0 0) (end 1 0) (width 0) (fill yes)))))'''
        board=PCB.replace('(via (size 0.6) (drill 0.3))','')[:-1]+pad+')'
        metrics=saved_metrics(board.encode(),PROJECT.encode())
        self.assertAlmostEqual(metrics.minimum_annular_ring_mm,.05)
        self.assertEqual(audit_metrics(metrics,FabricatorProfile())[3].status,'UNKNOWN')

    def test_unsupported_padstack_preserves_other_checks_and_blocks_release(self):
        pad='''(footprint "test" (pad "1" thru_hole circle (size 0.8 0.8) (drill 0.4)
          (layers "*.Cu") (padstack (mode front_inner_back)
            (layer "Inner" (shape custom) (size 0.7 0.7)))))'''
        board=PCB[:-1]+pad+')'
        checks=audit_metrics(saved_metrics(board.encode(),PROJECT.encode()),FabricatorProfile())
        statuses={check.item:check.status for check in checks}
        self.assertEqual(statuses['Minimum routed track'],'PASS')
        self.assertEqual(statuses['Minimum annular ring (plated pads and vias)'],'UNKNOWN')
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'board.kicad_pcb';source.write_text(board)
            with self.assertRaisesRegex(ValueError,'unknown'):
                build_release(Path(directory)/'release.zip',[source],checks,'test')

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
