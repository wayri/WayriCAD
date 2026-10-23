"""Native routing source identities cover changes hidden by bounding boxes."""
import unittest
from pathlib import Path
import tempfile
try:
    import pcbnew as p
except ImportError:
    p = None
from wayricad_runtime.geometry import board_fingerprint

@unittest.skipIf(p is None, 'Requires native KiCad Python')
class NativeFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.board = p.BOARD()
    def changed(self, mutate):
        before = board_fingerprint(self.board)
        mutate()
        self.assertNotEqual(before, board_fingerprint(self.board))
        self.assertEqual(board_fingerprint(self.board), board_fingerprint(self.board))
    def pad(self):
        fp = p.FOOTPRINT(self.board); self.board.Add(fp)
        pad = p.PAD(fp); fp.Add(pad)
        pad.SetSize(p.VECTOR2I(2000000, 2000000))
        return pad
    def test_keepout_flags(self):
        zone = p.ZONE(self.board); zone.SetIsRuleArea(True)
        zone.Outline().NewOutline()
        for x,y in ((0,0),(1000000,0),(1000000,1000000),(0,1000000)):
            zone.Outline().Append(x,y)
        self.board.Add(zone)
        for setter in ('SetDoNotAllowVias','SetDoNotAllowTracks','SetDoNotAllowPads',
                       'SetDoNotAllowFootprints','SetDoNotAllowZoneFills'):
            with self.subTest(setter=setter):
                self.changed(lambda: getattr(zone,setter)(not getattr(zone,setter.replace('Set','Get',1))()))
    def test_unsaved_live_manufacturing_floor_changes(self):
        settings=self.board.GetDesignSettings()
        for name in ('m_MinClearance','m_TrackMinWidth','m_ViasMinSize',
                     'm_ViasMinAnnularWidth','m_MinThroughDrill','m_HoleToHoleMin',
                     'm_MicroViasMinSize','m_MicroViasMinDrill',
                     'm_CopperEdgeClearance','m_HoleClearance'):
            if not hasattr(settings,name):
                continue
            with self.subTest(field=name):
                self.changed(lambda: setattr(settings,name,getattr(settings,name)+1000))
    def test_pad_iteration_order_survives_native_serialization(self):
        pad=self.pad(); fp=next(iter(self.board.GetFootprints())); pad.SetNumber('6')
        for number in ('5','4','3','2','1'):
            other=p.PAD(fp); other.SetNumber(number)
            other.SetPosition(p.VECTOR2I(int(number)*3000000,0)); fp.Add(other)
        before=board_fingerprint(self.board)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory,'roundtrip.kicad_pcb')
            self.assertTrue(p.SaveBoard(str(path),self.board))
            reloaded=p.LoadBoard(str(path))
            self.assertEqual(before,board_fingerprint(reloaded))
            changed_pad=next(iter(next(iter(reloaded.GetFootprints())).Pads()))
            changed_pad.SetOffset(p.VECTOR2I(100000,0))
            self.assertNotEqual(before,board_fingerprint(reloaded))
    def test_pad_shape_details(self):
        pad = self.pad(); pad.SetShape(p.PAD_SHAPE_ROUNDRECT)
        self.changed(lambda: pad.SetRoundRectRadiusRatio(.4))
        self.changed(lambda: pad.SetOffset(p.VECTOR2I(100000,0)))
        self.changed(lambda: pad.SetDrillSize(p.VECTOR2I(400000,600000)))
        self.changed(lambda: pad.SetDrillShape(p.PAD_DRILL_SHAPE_OBLONG))
        self.changed(lambda: pad.SetLocalClearance(100000))
    def test_custom_polygon(self):
        pad = self.pad(); pad.SetShape(p.PAD_SHAPE_CUSTOM)
        primitives=[]
        def primitive(a,b):
            shape=p.PCB_SHAPE(); shape.SetShape(p.SHAPE_T_SEGMENT)
            shape.SetStart(p.VECTOR2I(*a)); shape.SetEnd(p.VECTOR2I(*b)); shape.SetWidth(100000)
            pad.AddPrimitiveShape(p.F_Cu,shape)
            primitives.append(shape)
        primitive((-1000000,0),(1000000,0))
        self.changed(lambda: primitive((0,-1200000),(0,1200000)))
    def test_via_span_drill_type(self):
        self.board.SetCopperLayerCount(4)
        via = p.PCB_VIA(self.board); self.board.Add(via)
        via.SetWidth(600000); via.SetDrill(300000)
        self.changed(lambda: via.SetDrill(350000))
        self.changed(lambda: via.SetViaType(p.VIATYPE_BLIND))
        self.changed(lambda: via.SetLayerPair(p.F_Cu,p.In1_Cu))
    def test_track_arc_mid(self):
        arc = p.PCB_ARC(self.board); self.board.Add(arc)
        arc.SetStart(p.VECTOR2I(0,0)); arc.SetEnd(p.VECTOR2I(2000000,0)); arc.SetMid(p.VECTOR2I(1000000,500000))
        self.changed(lambda: arc.SetMid(p.VECTOR2I(1000000,-500000)))
    def test_footprint_edge_arc(self):
        fp=p.FOOTPRINT(self.board); self.board.Add(fp)
        shape=p.PCB_SHAPE(fp); shape.SetShape(p.SHAPE_T_ARC); shape.SetLayer(p.Edge_Cuts)
        shape.SetArcGeometry(p.VECTOR2I(0,0),p.VECTOR2I(1000000,500000),p.VECTOR2I(2000000,0)); fp.Add(shape)
        self.changed(lambda: shape.SetArcGeometry(p.VECTOR2I(0,0),p.VECTOR2I(1000000,-500000),p.VECTOR2I(2000000,0)))
    def test_edge_polygon_interior_vertex(self):
        shape = p.PCB_SHAPE(self.board); shape.SetShape(p.SHAPE_T_POLY); shape.SetLayer(p.Edge_Cuts)
        def poly(y):
            result=p.SHAPE_POLY_SET(); result.NewOutline()
            for x,v in ((0,0),(2000000,0),(2000000,2000000),(1000000,y),(0,2000000)):
                result.Append(x,v)
            return result
        shape.SetPolyShape(poly(1000000)); self.board.Add(shape)
        box=shape.GetBoundingBox()
        self.changed(lambda: shape.SetPolyShape(poly(1500000)))
        self.assertEqual((box.GetLeft(),box.GetTop(),box.GetRight(),box.GetBottom()),
            tuple(getattr(shape.GetBoundingBox(),f'Get{x}')() for x in ('Left','Top','Right','Bottom')))

if __name__=='__main__': unittest.main()
