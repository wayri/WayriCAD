"""PCB-only isolation, conservative layer/identity mapping and stale applies."""
import importlib
from pathlib import Path
import tempfile
import unittest

from test_sections import PACKAGE, sx, model

b=importlib.import_module(PACKAGE+'.board_layout')


def board(bottom=False):
    layer='B.Cu' if bottom else 'F.Cu'
    return sx.loads('''(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
      (net 0 "") (net 1 "GND")
      (footprint "Test:Part" (layer "'''+layer+'''") (at 5 5) (uuid "11111111-1111-4111-8111-111111111111")
       (property "Reference" "R1") (path "/schematic/symbol")
       (pad "1" smd rect (at 0 0) (size 1 1) (layers "'''+layer+'''") (net 1 "GND")))
      (segment (start 5 5) (end 6 5) (width 0.25) (layer "'''+layer+'''") (net 1)
       (uuid "22222222-2222-4222-8222-222222222222"))
      (via (at 6 5) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1)
       (uuid "33333333-3333-4333-8333-333333333333")))''')


class BoardLayoutTests(unittest.TestCase):
    def test_isolated_nets_board_only_references_outer_faces_and_fresh_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=sx.loads('(kicad_pcb (layers (0 "F.Cu" signal) (2 "In1.Cu" signal) (4 "In2.Cu" signal) (31 "B.Cu" signal)) (net 0 "") (net 1 "GND"))')
            source=board(True);before=sx.dumps(source)
            report,_=b._import_items(source,target,'Module',(10,20),root/'source.kicad_pcb',root)
            self.assertEqual(report['net_map'],{'GND':'/Module/GND'})
            fp=sx.children(target,'footprint')[0]
            self.assertEqual(sx.propval(fp,'Reference'),'Module_R1');self.assertEqual(sx.value(fp,'path'),'')
            self.assertEqual(sx.value(fp,'layer'),'B.Cu');self.assertIn('board_only',sx.child(fp,'attr'))
            self.assertEqual(sx.child(fp,'at')[1:3],['15','25'])
            self.assertEqual(b.net_name(sx.children(fp,'pad')[0],b.net_table(target)),'/Module/GND')
            self.assertEqual(list(sx.child(sx.children(target,'via')[0],'layers')[1:]),['F.Cu','B.Cu'])
            self.assertEqual(sx.dumps(source),before)
            self.assertTrue(set(sx.declared_uuids(source)).isdisjoint(sx.declared_uuids(target)))

    def test_duplicate_namespace_and_non_through_via_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=board()
            b._import_items(board(),target,'Module',(0,0),root/'source.kicad_pcb',root)
            with self.assertRaisesRegex(model.MergeError,'namespace'):
                b._import_items(board(),target,'Module',(0,0),root/'source.kicad_pcb',root)
            source=board();sx.children(source,'via')[0].insert(1,'blind')
            with self.assertRaisesRegex(model.MergeError,'through vias'):
                b._import_items(source,board(),'New',(0,0),root/'source.kicad_pcb',root)

    def test_new_drc_or_unconnected_finding_refused_and_existing_count_preserved(self):
        finding={'type':'clearance','severity':'error','items':[{'uuid':'a'}]}
        b._check_findings({'violations':[finding]},{'violations':[finding]})
        for category in ('violations','unconnected_items'):
            with self.assertRaises(model.MergeError):b._check_findings({}, {category:[finding]})
        with self.assertRaises(model.MergeError):b._check_findings({'violations':[finding]}, {'violations':[finding,finding]})
