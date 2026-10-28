"""Cold scalar imports and exact bounded reference-corridor acceleration."""
import importlib.util
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest


class ScalarImportTests(unittest.TestCase):
    def test_scalar_backend_does_not_import_optional_scientific_runtime(self):
        root=Path(__file__).resolve().parents[2]
        program="import sys;sys.path.insert(0,"+repr(str(root))+");from signal_integrity_advisor_plugin import rlc_model as r;assert 'scipy' not in sys.modules;assert r.EPS0==8.8541878188e-12;assert r.MU0==1.25663706127e-6;assert r.via_barrel(1,.3)['resistance_ohm']>0"
        result=subprocess.run([sys.executable,'-I','-c',program],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_pair_inventory_matches_individual_rules_and_consumes_generator_once(self):
        from signal_integrity_advisor_plugin.diff_pairs import detect_pairs,find_mate,classify_pair
        names=['DATA_P','DATA_N','clock+','clock-','TXP','TXN','CAP','CAN','rx_p','rx_n','Other']
        expected=[];taken=set();ordered=sorted(set(names))
        for net in ordered:
            if net in taken:continue
            mate=find_mate(net,ordered)
            if not mate or mate==net:continue
            pair=classify_pair(net,mate) or classify_pair(mate,net)
            if pair is not None:expected.append(pair);taken.update((net,mate))
        self.assertEqual(detect_pairs(n for n in names),expected)
        self.assertEqual(find_mate('DATA_P',(n for n in names)),'DATA_N')


try:
    import pcbnew
except ImportError:
    pcbnew=None


@unittest.skipIf(pcbnew is None,'Native KiCad polygon engine required')
class NativeCorridorTests(unittest.TestCase):
    def geometry(self):
        from signal_integrity_advisor_plugin.copper_path import CopperGeometry
        board=pcbnew.BOARD();board.SetCopperLayerCount(2)
        return CopperGeometry(SimpleNamespace(board=board))

    def test_tile_clipping_matches_full_plane_subtraction_with_holes_and_boundaries(self):
        g=self.geometry();iu=1_000_000
        poly=g.polygon([(-50*iu,-30*iu),(60*iu,-30*iu),(60*iu,40*iu),(-50*iu,40*iu)])
        for x,y in ((0,0),(24.9,10),(-25,-10)):
            hole=pcbnew.SHAPE_LINE_CHAIN()
            for dx,dy in ((-1,-1),(1,-1),(1,1),(-1,1)):hole.Append(round((x+dx)*iu),round((y+dy)*iu))
            hole.SetClosed(True);poly.AddHole(hole,0)
        island={'poly':poly}
        cases=[((-10,0),(10,0),.2),((-10,3),(10,3),.2),((-49.9,-29.9),(-40,-29.9),.2),
               ((24,9),(27,12),.1),((-30,-12),(-20,-12),.5),((24.999,-5),(25.001,5),.2)]
        cases += [((-45+i*1.1,-20+(i%7)),(-40+i*1.1,-19+(i%7)),.15) for i in range(64)]
        for a,b,width in cases:
            a,b=tuple(round(v*iu) for v in a),tuple(round(v*iu) for v in b)
            expected=False
            if poly.Contains(pcbnew.VECTOR2I(*a)) and poly.Contains(pcbnew.VECTOR2I(*b)):
                original=g.corridor(a,b,width);original.BooleanSubtract(poly);expected=original.Area()<=4
            with self.subTest(a=a,b=b,width=width):
                self.assertEqual(g.fits(island,a,b,width),expected)
                self.assertEqual(g.fits(island,a,b,width),expected)
        self.assertLessEqual(len(g._reference_tiles),128)
        self.assertLessEqual(len(g._fit_cache),8192)

    def test_new_geometry_after_edit_does_not_keep_old_containment(self):
        first=self.geometry();second=self.geometry();iu=1_000_000
        broad=first.polygon([(0,0),(10*iu,0),(10*iu,10*iu),(0,10*iu)])
        narrow=second.polygon([(0,0),(4*iu,0),(4*iu,10*iu),(0,10*iu)])
        self.assertTrue(first.fits({'poly':broad},(2*iu,5*iu),(8*iu,5*iu),.2))
        self.assertFalse(second.fits({'poly':narrow},(2*iu,5*iu),(8*iu,5*iu),.2))


@unittest.skipIf(pcbnew is None,'Native plugin imports required')
class TestPointSnapshotTests(unittest.TestCase):
    def test_shared_snapshot_preserves_routes_and_refreshes_after_field_edits(self):
        from signal_integrity_advisor_plugin.test_points.test_point_descriptor_plugin import extract_test_points
        class Pad:
            def __init__(self,number,net):self.number=number;self.net=net
            def GetNetname(self):return self.net
            def GetNumber(self):return self.number
            def GetPinFunction(self):return 'input'
        class Field:
            def __init__(self,name,value):self.name=name;self.value=value
            def GetName(self):return self.name
            def GetText(self):return self.value
        class Footprint:
            def __init__(self,reference,pads,fields=None):self.reference=reference;self.pads=pads;self.fields=fields or {};self.reads=0
            def GetReference(self):return self.reference
            def GetValue(self):return self.reference
            def Pads(self):return self.pads
            def GetFields(self):self.reads+=1;return [Field(k,v) for k,v in self.fields.items()]
        class Board:
            def __init__(self,parts):self.parts=parts;self.reads=0
            def GetFootprints(self):self.reads+=1;return self.parts
        bridge=Footprint('Z1',[Pad('1','A'),Pad('2','B')],{'NetTie_Path':'reviewed'})
        board=Board([Footprint('TP1',[Pad('1','A')]),Footprint('TP2',[Pad('1','A')]),bridge,
                     Footprint('U1',[Pad('1','B')])])
        first=extract_test_points(board)
        self.assertEqual([r['Connected IC'] for r in first],['U1','U1'])
        self.assertEqual(board.reads,2)
        self.assertEqual(bridge.reads,1)
        self.assertEqual(first[0]['Trace Path'],'[A] -> Z1.1 -> Z1.2 -> [B] -> U1.1')
        bridge.fields={};second=extract_test_points(board)
        self.assertEqual([r['Connected IC'] for r in second],['',''])
        self.assertEqual(board.reads,4)


if __name__=='__main__':unittest.main()
