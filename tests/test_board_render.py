"""Display-only native geometry: holes, layers and exact copper ownership."""
import json
import unittest
from wayricad_runtime.board_render import extract_board, hit_test, visible_primitives, _rings
try:
    import pcbnew as p
except ImportError:
    p = None


class DisplayGeometryTests(unittest.TestCase):
    def test_holes_and_layer_filters_do_not_create_copper_hits(self):
        row = dict(kind='polygon', role='zone', layer=0, uuid='zone', net='VCC',
                   points=[[0,0],[10,0],[10,10],[0,10]], holes=[[[4,4],[6,4],[6,6],[4,6]]])
        scene = {'primitives': [row,dict(row,layer=31,net='GND',uuid='other')]}
        self.assertEqual(hit_test(scene,5,5),[])
        self.assertEqual([r['uuid'] for r in hit_test(scene,2,2,[0],'VCC')],['zone'])
        self.assertEqual(hit_test(scene,2,2,[31],'VCC'),[])
        self.assertEqual(len(visible_primitives(scene,[31])),1)
        outer,hole = _rings(row)
        def area(r): return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(r,r[1:]+r[:1]))
        self.assertGreater(area(outer)*-area(hole),0)


@unittest.skipIf(p is None,'Requires KiCad native PCB geometry')
class NativeBoardRenderTests(unittest.TestCase):
    def test_reference_uses_saved_visible_glyph_geometry_not_centroid_text(self):
        board=p.BOARD();fp=p.FOOTPRINT(board);board.Add(fp);fp.SetReference('R123')
        fp.SetPosition(p.VECTOR2I(p.FromMM(5),p.FromMM(5)))
        field=fp.Reference();field.SetVisible(True);field.SetLayer(p.F_SilkS)
        field.SetPosition(p.VECTOR2I(p.FromMM(12),p.FromMM(8)))
        field.SetTextSize(p.VECTOR2I(p.FromMM(.7),p.FromMM(.7)))
        field.SetTextAngle(p.EDA_ANGLE(45,p.DEGREES_T));fp.Value().SetVisible(False)
        scene=extract_board(board)
        self.assertFalse(any(row['kind']=='text' for row in scene['primitives']))
        rows=[row for row in scene['primitives'] if row['role']=='reference']
        self.assertTrue(rows);self.assertTrue(all(row['layer']==p.F_SilkS for row in rows))
        poly=p.SHAPE_POLY_SET();field.TransformShapeToPolygon(poly,p.F_SilkS,0,p.FromMM(.01),p.ERROR_INSIDE)
        expected=[[[p.ToMM(pt.x),p.ToMM(pt.y)] for pt in poly.COutline(i).CPoints()] for i in range(poly.OutlineCount())]
        self.assertEqual([row['points'] for row in rows],expected)
        field.SetVisible(False)
        self.assertFalse(any(row['role']=='reference' for row in extract_board(board)['primitives']))

    def test_saved_native_copper_width_drills_and_pad_ownership(self):
        board=p.BOARD()
        point=lambda x,y:p.VECTOR2I(p.FromMM(x),p.FromMM(y))
        track=p.PCB_TRACK(board);track.SetStart(point(1,1));track.SetEnd(point(10,1))
        track.SetWidth(p.FromMM(.5));track.SetLayer(p.F_Cu);board.Add(track)
        via=p.PCB_VIA(board);via.SetPosition(point(5,5));via.SetWidth(p.FromMM(1))
        via.SetDrill(p.FromMM(.4));via.SetLayerPair(p.F_Cu,p.B_Cu);board.Add(via)
        fp=p.FOOTPRINT(board);fp.SetReference('J1');board.Add(fp)
        pad=p.PAD(fp);pad.SetPosition(point(3,3));pad.SetSize(point(2,2))
        pad.SetAttribute(p.PAD_ATTRIB_SMD);layers=p.LSET();layers.AddLayer(p.F_Cu);pad.SetLayerSet(layers);fp.Add(pad)
        scene=extract_board(board)
        json.dumps(scene,allow_nan=False)
        self.assertEqual([r['uuid'] for r in hit_test(scene,3,1,[p.F_Cu])],[track.m_Uuid.AsString()])
        self.assertEqual(hit_test(scene,3,1.3,[p.F_Cu]),[])
        self.assertEqual(hit_test(scene,5,5),[])
        self.assertTrue(hit_test(scene,5.35,5,[p.F_Cu]))
        pads=hit_test(scene,3,3,[p.F_Cu])
        self.assertEqual(pads[0]['reference'],'J1')
        self.assertEqual(pads[0]['parent_uuid'],fp.m_Uuid.AsString())
        self.assertTrue(any('closed outline' in w for w in scene['warnings']))

    def test_scoped_extraction_keeps_exact_native_net_geometry(self):
        board=p.BOARD()
        for index,name in enumerate(('VCC','VCC_AUX','GND'),1):
            net=p.NETINFO_ITEM(board,name,index);board.Add(net)
            track=p.PCB_TRACK(board);track.SetNet(net);track.SetLayer(p.F_Cu)
            track.SetStart(p.VECTOR2I(p.FromMM(index),p.FromMM(1)))
            track.SetEnd(p.VECTOR2I(p.FromMM(index),p.FromMM(5)))
            track.SetWidth(p.FromMM(.3));board.Add(track)
        complete=extract_board(board)
        focused=extract_board(board,['VCC'])
        expected=[row for row in complete['primitives'] if row.get('net')=='VCC']
        self.assertEqual(focused['primitives'],expected)
        self.assertEqual(focused['net_scope'],['VCC'])
        self.assertEqual(len(list(board.GetTracks())),3)
        self.assertEqual(extract_board(board)['primitives'],complete['primitives'])

    def test_saved_fill_voids_are_preserved_and_no_fill_is_invented(self):
        b=p.BOARD();poly=p.SHAPE_POLY_SET();poly.NewOutline()
        for x,y in ((0,0),(10,0),(10,10),(0,10)):poly.Append(p.FromMM(x),p.FromMM(y))
        h=poly.NewHole()
        for x,y in ((4,4),(4,6),(6,6),(6,4)):poly.Append(p.FromMM(x),p.FromMM(y),0,h)
        z=p.ZONE(b);z.SetLayer(p.F_Cu);z.Outline().Append(poly);z.SetFilledPolysList(p.F_Cu,poly);z.SetIsFilled(True);b.Add(z)
        empty=p.ZONE(b);empty.SetLayer(p.B_Cu);empty.Outline().Append(poly);b.Add(empty)
        scene=extract_board(b)
        self.assertEqual(hit_test(scene,5,5),[])
        self.assertEqual(len(hit_test(scene,2,2)),1)
        self.assertTrue(any('no saved fill' in w for w in scene['warnings']))


if __name__=='__main__': unittest.main()
