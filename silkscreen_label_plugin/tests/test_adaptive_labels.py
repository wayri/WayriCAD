"""Per-label adaptive sizing and checked nearby guide placement."""
import unittest
import test_placement as fixture
from silkscreen_label_plugin import placement as m
p=fixture.api

@unittest.skipIf(p is None,'Native KiCad required')
class AdaptiveLabelTests(unittest.TestCase):
    def test_whole_board_associations_are_straight_and_do_not_cross_text_or_each_other(self):
        board=fixture.dense_board(p,4,3)
        review=m.plan(board,p)
        self.assertEqual(review.stats['placed'],12)
        changes=review.changes
        self.assertEqual(len(changes),12)
        for index,change in enumerate(changes):
            self.assertEqual(len(change.sightline),2)
            self.assertLessEqual(len(change.leader_path),2)
            first,second=change.sightline
            for other in changes[:index]:
                self.assertGreater(m.segment_segment_distance(first,second,*other.sightline),0)
                self.assertFalse(m.segment_hits_box(p.VECTOR2I(*first),p.VECTOR2I(*second),other.box))
                self.assertFalse(m.segment_hits_box(p.VECTOR2I(*other.sightline[0]),p.VECTOR2I(*other.sightline[1]),change.box))
        self.assertTrue(all(row['envelope_gap_mm']<=2 for row in review.outcomes))
        self.assertTrue(all(row['courtyard_gap_mm'] is None for row in review.outcomes))

    def test_whole_board_reports_every_reference_including_unchanged(self):
        board=fixture.dense_board(p,4,3)
        source=m.fingerprint(board,p)
        review=m.plan(board,p,dict(body_clearance=.2))
        self.assertEqual(source,m.fingerprint(board,p))
        self.assertEqual(len(review.outcomes),12)
        self.assertEqual({row['id'] for row in review.outcomes},
                         {m.item_id(fp.Reference()) for fp in board.GetFootprints()})
        self.assertTrue(all(row['candidate_checks']>0 for row in review.outcomes))
        self.assertEqual(review.stats['reviewed'],12)
        tx=m.apply(board,p,review)
        second=m.plan(board,p)
        self.assertEqual(len(second.outcomes),12)
        self.assertTrue(all(row['status']=='UNCHANGED' for row in second.outcomes))
        tx.undo();self.assertEqual(source,m.fingerprint(board,p))

    def test_every_unresolved_reference_gets_automatic_retry(self):
        case=fixture.PlacementTests();case.setUp()
        case.pad.SetSize(case.v(20,20))
        source=m.fingerprint(case.board,p)
        messages=[]
        review=m.plan(case.board,p,dict(max_radius=.1),
                      progress=lambda done,total,label:messages.append(label) or True)
        self.assertEqual(source,m.fingerprint(case.board,p))
        self.assertEqual(review.stats['reviewed'],1)
        self.assertEqual(review.stats['repair_attempts'],1)
        self.assertTrue(review.outcomes[0]['retried'])
        self.assertEqual(review.outcomes[0]['status'],'UNRESOLVED')
        self.assertTrue(any(label.startswith('Retry unresolved: ') for label in messages))
        with self.assertRaisesRegex(ValueError,'cancelled'):
            m.plan(case.board,p,dict(max_radius=.1),
                   progress=lambda done,total,label:not label.startswith('Retry unresolved: '))
        self.assertEqual(source,m.fingerprint(case.board,p))

    def test_spatial_index_removes_owner_without_removing_neighbours(self):
        index=m._SpatialIndex(p.FromMM(4))
        box=p.BOX2I(p.VECTOR2I(0,0),p.VECTOR2I(p.FromMM(5),p.FromMM(5)))
        index.add(box,'first');index.add(box,'second')
        index.discard('first')
        self.assertEqual([key for _,key in index.query(box)],['second'])
        index.add(box,'first')
        self.assertEqual([key for _,key in index.query(box)],['second','first'])

    def test_tented_via_reserves_drill_instead_of_covered_annulus(self):
        board=fixture.dense_board(p,1,1)
        via=p.PCB_VIA(board);via.SetPosition(p.VECTOR2I(p.FromMM(5),p.FromMM(5)))
        via.SetWidth(p.FromMM(.8));via.SetDrill(p.FromMM(.3))
        via.SetLayerPair(p.F_Cu,p.B_Cu);board.Add(via)
        via.SetFrontTentingMode(p.TENTING_MODE_TENTED)
        via.SetBackTentingMode(p.TENTING_MODE_NOT_TENTED)
        self.assertIsNone(m.via_silkscreen_obstacle(via,p.F_SilkS,p))
        front=m.via_silkscreen_obstacle(via,p.F_SilkS,p,protect_tented_drills=True)
        back=m.via_silkscreen_obstacle(via,p.B_SilkS,p)
        self.assertEqual(front.GetWidth(),p.FromMM(.3))
        self.assertGreaterEqual(back.GetWidth(),p.FromMM(.8))
        self.assertTrue(front.Contains(via.GetPosition()))
        # A top-to-inner blind via has no bottom-side opening or drill exit.
        via.SetViaType(p.VIATYPE_BLIND)
        via.SetLayerPair(p.F_Cu,p.In1_Cu)
        self.assertIsNone(m.via_silkscreen_obstacle(via,p.B_SilkS,p))

    def test_via_tenting_and_layer_span_invalidate_preview_and_undo(self):
        for change in ('tenting','span'):
            with self.subTest(change=change):
                case=fixture.PlacementTests();case.setUp()
                via=p.PCB_VIA(case.board);via.SetPosition(case.v(30,30))
                via.SetWidth(p.FromMM(.8));via.SetDrill(p.FromMM(.3))
                via.SetLayerPair(p.F_Cu,p.B_Cu);case.board.Add(via)
                via.SetFrontTentingMode(p.TENTING_MODE_TENTED)
                review=m.plan(case.board,p)
                before=m.fingerprint(case.board,p)
                if change=='tenting':via.SetFrontTentingMode(p.TENTING_MODE_NOT_TENTED)
                else:
                    via.SetViaType(p.VIATYPE_BLIND);via.SetLayerPair(p.F_Cu,p.In1_Cu)
                self.assertNotEqual(before,m.fingerprint(case.board,p))
                with self.assertRaisesRegex(ValueError,'changed'):m.apply(case.board,p,review)
                fresh=m.plan(case.board,p);tx=m.apply(case.board,p,fresh)
                via.SetFrontTentingMode(p.TENTING_MODE_NOT_TENTED if change=='span' else p.TENTING_MODE_TENTED)
                with self.assertRaisesRegex(ValueError,'changed'):tx.undo()

    def test_fabrication_references_are_explicitly_accounted_for(self):
        case=fixture.PlacementTests();case.setUp()
        case.text.SetLayer(p.F_Fab)
        before=m.fingerprint(case.board,p)
        review=m.plan(case.board,p)
        self.assertEqual(review.stats['eligible'],0)
        self.assertTrue(any('F.Fab' in reason and 'outside silkscreen scope' in reason
                            for _,reason in review.skipped))
        self.assertEqual(before,m.fingerprint(case.board,p))

    def test_one_plan_uses_different_sizes_for_different_spaces(self):
        # The visible glyph envelope, unlike font padding, fits at full size
        # on the old 3.4 mm pitch. This tighter pitch requires real shrinking.
        board=fixture.dense_board(p,6,3,pitch=2.95)
        for fp in board.GetFootprints():
            c=fp.GetPosition();x=p.FromMM(1.1);y=p.FromMM(.7)
            corners=[(c.x-x,c.y-y),(c.x+x,c.y-y),(c.x+x,c.y+y),(c.x-x,c.y+y)]
            for i,a in enumerate(corners):
                shape=p.PCB_SHAPE(fp);shape.SetLayer(p.F_CrtYd);shape.SetShape(p.SHAPE_T_SEGMENT)
                shape.SetWidth(p.FromMM(.05));shape.SetStart(p.VECTOR2I(*a));shape.SetEnd(p.VECTOR2I(*corners[(i+1)%4]));fp.Add(shape)
        source=m.fingerprint(board,p);review=m.plan(board,p,dict(body_clearance=.2))
        self.assertEqual(source,m.fingerprint(board,p))
        self.assertEqual(review.stats['placed'],18)
        heights={c.size[1] for c in review.changes}
        self.assertGreater(len(heights),1)
        self.assertTrue(all(board.GetDesignSettings().m_MinSilkTextHeight<=h<=p.FromMM(1) for h in heights))
        tx=m.apply(board,p,review)
        self.assertEqual({fp.Reference().GetTextSize().y for fp in board.GetFootprints()},heights)
        tx.undo();self.assertEqual(source,m.fingerprint(board,p))

    def test_adjacent_large_body_does_not_get_spurious_centre_distance_guide(self):
        case=fixture.PlacementTests();case.setUp()
        case.pad.SetSize(case.v(8,8))
        review=m.plan(case.board,p,dict(leader_distance=3))
        self.assertTrue(review.changes)
        change=review.changes[0]
        body=m.courtyard_envelopes(case.fp,p)[p.F_SilkS]
        self.assertLess(m.box_distance(change.box,body),p.FromMM(.3))
        self.assertGreater(((change.position[0]-case.fp.GetPosition().x)**2+
                            (change.position[1]-case.fp.GetPosition().y)**2)**.5,p.FromMM(3))
        self.assertFalse(change.leader_path)

    def test_no_local_room_places_label_nearby_with_checked_guide(self):
        case=fixture.PlacementTests();case.setUp()
        case.pad.SetSize(case.v(8,8))
        source=m.fingerprint(case.board,p)
        review=m.plan(case.board,p,dict(leaders=True,max_radius=8,leader_distance=.1,body_clearance=.2))
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
        # The label is next to the large body despite its distant origin.
        self.assertLess(m.box_distance(change.box,m.courtyard_envelopes(case.fp,p)[p.F_SilkS]),p.FromMM(.3))
        self.assertFalse(change.leader_path)
        self.assertFalse(change.box.Intersects(case.pad.GetBoundingBox()))
        tx=m.apply(case.board,p,review);tx.undo()
        self.assertEqual(source,m.fingerprint(case.board,p))

if __name__=='__main__':unittest.main()
