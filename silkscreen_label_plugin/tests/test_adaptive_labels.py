"""Per-label adaptive sizing and checked nearby guide placement."""
import unittest
import test_placement as fixture
from silkscreen_label_plugin import placement as m
p=fixture.api

@unittest.skipIf(p is None,'Native KiCad required')
class AdaptiveLabelTests(unittest.TestCase):
    def test_one_plan_uses_different_sizes_for_different_spaces(self):
        board=fixture.dense_board(p,6,3)
        for fp in board.GetFootprints():
            c=fp.GetPosition();x=p.FromMM(1.1);y=p.FromMM(.7)
            corners=[(c.x-x,c.y-y),(c.x+x,c.y-y),(c.x+x,c.y+y),(c.x-x,c.y+y)]
            for i,a in enumerate(corners):
                shape=p.PCB_SHAPE(fp);shape.SetLayer(p.F_CrtYd);shape.SetShape(p.SHAPE_T_SEGMENT)
                shape.SetWidth(p.FromMM(.05));shape.SetStart(p.VECTOR2I(*a));shape.SetEnd(p.VECTOR2I(*corners[(i+1)%4]));fp.Add(shape)
        source=m.fingerprint(board,p);review=m.plan(board,p)
        self.assertEqual(source,m.fingerprint(board,p))
        self.assertEqual(review.stats['placed'],18)
        heights={c.size[1] for c in review.changes}
        self.assertGreater(len(heights),1)
        self.assertTrue(all(board.GetDesignSettings().m_MinSilkTextHeight<=h<=p.FromMM(1) for h in heights))
        tx=m.apply(board,p,review)
        self.assertEqual({fp.Reference().GetTextSize().y for fp in board.GetFootprints()},heights)
        tx.undo();self.assertEqual(source,m.fingerprint(board,p))

    def test_no_local_room_places_label_nearby_with_checked_guide(self):
        case=fixture.PlacementTests();case.setUp()
        case.pad.SetSize(case.v(8,8))
        source=m.fingerprint(case.board,p)
        review=m.plan(case.board,p,dict(max_radius=8,leader_distance=1))
        self.assertTrue(review.changes);change=review.changes[0]
        self.assertTrue(change.leader_path)
        self.assertLessEqual(((change.position[0]-case.fp.GetPosition().x)**2+(change.position[1]-case.fp.GetPosition().y)**2)**.5,p.FromMM(8))
        self.assertFalse(change.box.Intersects(case.pad.GetBoundingBox()))
        for a,b,c,d,width,layer in m._leader_segments(change):
            self.assertFalse(m.segment_hits_box(p.VECTOR2I(a,b),p.VECTOR2I(c,d),case.pad.GetBoundingBox(),p.FromMM(.2)+width//2))
        tx=m.apply(case.board,p,review);self.assertTrue(tx.leaders)
        tx.undo();self.assertEqual(source,m.fingerprint(case.board,p))

    def test_large_component_search_starts_at_footprint_edge(self):
        case=fixture.PlacementTests();case.setUp()
        case.pad.SetSize(case.v(26,26))
        source=m.fingerprint(case.board,p)
        review=m.plan(case.board,p,dict(max_radius=12,leader_distance=3))
        self.assertEqual(len(review.changes),1)
        change=review.changes[0]
        distance=((change.position[0]-case.fp.GetPosition().x)**2+(change.position[1]-case.fp.GetPosition().y)**2)**.5
        self.assertGreater(distance,p.FromMM(12))
        self.assertTrue(change.leader_path)
        self.assertFalse(change.box.Intersects(case.pad.GetBoundingBox()))
        tx=m.apply(case.board,p,review);tx.undo()
        self.assertEqual(source,m.fingerprint(case.board,p))

if __name__=='__main__':unittest.main()
