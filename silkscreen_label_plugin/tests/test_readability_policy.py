"""Native acceptance cases for conservative reference correction defaults."""
import unittest
from unittest.mock import patch
import test_placement as fixture
import test_label_ownership as ownership
from silkscreen_label_plugin import placement as m
from silkscreen_label_plugin import lifecycle

p=fixture.api

@unittest.skipIf(p is None,'Native KiCad required')
class ReadabilityPolicyTests(unittest.TestCase):
    def case(self):
        case=ownership.LabelOwnershipTests();case.setUp();return case

    def test_good_existing_reference_is_preserved_in_both_normal_and_problem_modes(self):
        case=self.case();case.pad.SetSize(case.v(.4,.4));case.courtyard(case.fp)
        case.text.SetPosition(case.v(20,18.2))
        for problem_only in (False,True):
            review=m.plan(case.board,p,dict(problem_only=problem_only))
            self.assertFalse(review.changes)
            self.assertEqual(review.stats['placed'],1)
            self.assertTrue(review.outcomes[0]['preserved_acceptable'])
        self.assertFalse(m.DEFAULTS['leaders'])

    def test_axis_preference_and_common_direction_are_explicit_alternatives(self):
        case=self.case();case.fp.SetOrientationDegrees(90);case.courtyard(case.fp,1.2,1.2)
        for preference,angle in (('Footprint axis',90),('Common direction',0)):
            review=m.plan(case.board,p,dict(orientation_preference=preference,allowed_rotations=(0,90)))
            self.assertEqual(review.stats['placed'],1)
            self.assertEqual(review.changes[0].after[2]%180,angle)

    def test_short_leaders_obey_the_boardwide_count_budget(self):
        board=fixture.dense_board(p,3,1,pitch=8)
        review=m.plan(board,p,dict(leaders=True,leader_limit=1,leader_max_length=3,
                                 leader_distance=.1,body_clearance=.2))
        self.assertEqual(review.stats['placed'],1)
        self.assertEqual(len(review.rejected),2)
        self.assertEqual(sum(bool(c.leader) for c in review.changes),1)
        self.assertEqual(review.stats['guides'],1)
        self.assertEqual(review.stats['guide_budget_limited'],2)
        self.assertEqual(sum(row['guide_budget_limited'] for row in review.outcomes),2)
        self.assertTrue(all('guide count' in reason for label,reason in review.rejected))
        self.assertTrue(all(len(c.leader_path)==2 for c in review.changes))

    def test_selection_counts_verified_guides_retained_outside_its_scope(self):
        board=fixture.dense_board(p,3,1,pitch=8)
        settings=dict(leaders=True,leader_limit=1,leader_max_length=3,
                      leader_distance=.1,body_clearance=.2)
        initial=m.plan(board,p,settings)
        self.assertEqual(initial.stats['guides'],1)
        m.apply(board,p,initial)
        placed={m.item_id(change.footprint) for change in initial.changes}
        other=next(fp for fp in board.GetFootprints() if m.item_id(fp) not in placed)
        other.SetSelected()
        before=m.fingerprint(board,p)
        selected=m.plan(board,p,dict(settings,selected_only=True))
        self.assertEqual(selected.stats['placed'],0)
        self.assertEqual(selected.stats['guides'],1)
        self.assertEqual(selected.stats['guide_budget_limited'],1)
        self.assertFalse(selected.changes)
        self.assertEqual(m.fingerprint(board,p),before)

    def test_width_compression_fits_only_within_explicit_readability_limits(self):
        board=p.BOARD();text=p.PCB_TEXT(board);text.SetText('WWWW');text.SetLayer(p.F_SilkS)
        text.SetTextSize(p.VECTOR2I(p.FromMM(1),p.FromMM(.8)));text.SetTextThickness(p.FromMM(.12))
        board.Add(text);state=m._state(text)
        full=m._box(text,state,p);narrow=m._box(text,state[:3]+(p.FromMM(.6),)+state[4:],p)
        width=(full.GetWidth()+narrow.GetWidth())//2+p.FromMM(.4)
        height=p.FromMM(6);points=[(0,0),(width,0),(width,height),(0,height)]
        for a,b in zip(points,points[1:]+points[:1]):
            edge=p.PCB_SHAPE(board);edge.SetShape(p.SHAPE_T_SEGMENT);edge.SetLayer(p.Edge_Cuts)
            edge.SetStart(p.VECTOR2I(*a));edge.SetEnd(p.VECTOR2I(*b));board.Add(edge)
        text.SetPosition(p.VECTOR2I(width//2,height//2))
        review=m.plan(board,p,dict(references=False,board_text=True,height=.8,min_height=.8,
            min_width=.6,min_width_ratio=.75,allowed_rotations=(0,)))
        self.assertEqual(review.stats['placed'],1)
        change=review.changes[0]
        self.assertEqual(change.after[3],p.FromMM(.6))
        self.assertEqual(change.after[4],p.FromMM(.8))
        self.assertGreaterEqual(change.box.GetLeft(),p.FromMM(.2))
        self.assertLessEqual(change.box.GetRight(),width-p.FromMM(.2))

    def test_property_write_failure_after_mutation_rolls_back_generation(self):
        case=self.case();review=m.plan(case.board,p);before=m.fingerprint(case.board,p)
        setter=case.board.SetProperties;calls=[]
        def fail_once(properties):
            setter(properties);calls.append(1)
            if len(calls)==1:raise RuntimeError('Injected metadata failure')
        with patch.object(case.board,'SetProperties',side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError,'Injected metadata'):m.apply(case.board,p,review)
        self.assertEqual(m.fingerprint(case.board,p),before)

    def test_other_board_metadata_change_rejects_undo_without_overwriting_it(self):
        case=self.case();tx=m.apply(case.board,p,m.plan(case.board,p))
        properties=lifecycle._properties(case.board);properties['external-note']='Keep this value'
        case.board.SetProperties(lifecycle._native_properties(p,properties))
        with self.assertRaisesRegex(ValueError,'changed'):tx.undo()
        self.assertEqual(lifecycle._properties(case.board)['external-note'],'Keep this value')

    def test_legacy_named_artwork_is_reported_and_never_adopted_or_deleted(self):
        case=self.case();shape=p.PCB_SHAPE(case.board)
        shape.SetShape(p.SHAPE_T_SEGMENT);shape.SetLayer(p.F_SilkS)
        shape.SetStart(case.v(1,1));shape.SetEnd(case.v(3,1));case.board.Add(shape)
        group=p.PCB_GROUP(case.board);group.SetName(m.GUIDE_PREFIX+m.item_id(case.text))
        group.AddItem(shape);case.board.Add(group)
        before=m.fingerprint(case.board,p);review=m.plan(case.board,p)
        self.assertTrue(any('legacy' in str(row).lower() for row in review.skipped))
        tx=m.apply(case.board,p,review)
        self.assertIn(m.item_id(shape),{m.item_id(x) for x in case.board.GetDrawings()})
        self.assertIn(m.item_id(group),{m.item_id(x) for x in case.board.Groups()})
        self.assertEqual(lifecycle.audit(case.board,p).as_dict()['cleanup_group_ids'],[])
        tx.undo();self.assertEqual(m.fingerprint(case.board,p),before)

    def test_fabrication_body_outside_an_undersized_courtyard_is_protected(self):
        case=self.case();case.pad.SetSize(case.v(.4,.4));case.courtyard(case.fp)
        shape=p.PCB_SHAPE(case.fp);shape.SetShape(p.SHAPE_T_RECT);shape.SetLayer(p.F_Fab)
        shape.SetStart(case.v(18,18));shape.SetEnd(case.v(22,22));case.fp.Add(shape)
        review=m.plan(case.board,p)
        self.assertEqual(review.stats['placed'],1)
        change=review.changes[0]
        self.assertFalse(change.box.Intersects(shape.GetBoundingBox()))
        outcome=review.outcomes[0]
        self.assertGreater(outcome['courtyard_gap_mm'],outcome['body_hull_gap_mm'])


@unittest.skipIf(p is None,'Native KiCad required')
class SearchPhaseRegressionTests(unittest.TestCase):
    def test_crowded_local_search_does_not_starve_a_legal_far_position(self):
        case=ownership.LabelOwnershipTests();case.setUp()
        case.fp.Reference().SetVisible(False);case.fp.Value().SetVisible(False)
        case.pad.SetSize(case.v(6,6))
        text=p.PCB_TEXT(case.board);text.SetLayer(p.F_SilkS);text.SetText('R100')
        text.SetPosition(case.v(20,20));text.SetTextSize(case.v(1.2,1.2))
        text.SetTextThickness(p.FromMM(.12));case.board.Add(text)
        before=m.fingerprint(case.board,p)
        # Isolate candidate allocation from machine speed. There are many valid
        # size/angle combinations, but every position within 2 mm hits the pad.
        with patch.object(m.time,'monotonic',return_value=0):
            review=m.plan(case.board,p,dict(references=False,board_text=True,
                preserve_acceptable=False,allowed_rotations=tuple(range(0,180,5)),
                height=1.2,min_height=.8,size_step=.1,min_width=.6,
                min_width_ratio=.5,max_radius=12))
        self.assertEqual(review.stats['placed'],1)
        self.assertEqual(before,m.fingerprint(case.board,p))
        change=review.changes[0]
        self.assertGreater((change.after[0]-p.FromMM(20))**2+
                           (change.after[1]-p.FromMM(20))**2,p.FromMM(2)**2)
        self.assertFalse(m._inflate(change.box,p.FromMM(.2),p).Intersects(case.pad.GetBoundingBox()))
        self.assertFalse(change.leader_path)
        tx=m.apply(case.board,p,review);tx.undo()
        self.assertEqual(before,m.fingerprint(case.board,p))

    def test_cluster_repacking_respects_explicit_neighbour_displacement(self):
        import math
        import sys
        from types import SimpleNamespace
        for displacement in (0,2):
            with self.subTest(displacement=displacement):
                case=ownership.LabelOwnershipTests();case.setUp()
                case.fp.SetReference('R1');case.pad.SetSize(case.v(.4,.4));case.courtyard(case.fp)
                neighbour=case.other_part('R2',22,20);case.courtyard(neighbour)
                text=neighbour.Reference();text.SetVisible(True);text.SetLayer(p.F_SilkS)
                text.SetTextSize(case.v(1,1));text.SetTextThickness(p.FromMM(.15))
                text.SetPosition(case.v(20,18.8))
                before=m.fingerprint(case.board,p);contexts=[]
                # Capture the native planner's prepared cluster assignment. The
                # test supplies one reviewed target slot rather than relying on
                # board-wide greedy order to reproduce this two-label conflict.
                class Prepared(Exception):pass
                def capture(frame,event,arg):
                    if event=='call' and frame.f_code.co_name=='assign' and frame.f_back.f_code.co_name=='plan':
                        contexts.append(dict(frame.f_back.f_locals));raise Prepared()
                    return None
                previous=sys.gettrace();sys.settrace(capture)
                try:
                    with self.assertRaises(Prepared):
                        m.plan(case.board,p,dict(repack_displacement=displacement,
                            preserve_acceptable=False,allowed_rotations=(0,),leaders=False))
                finally:sys.settrace(previous)
                context=contexts[-1];target_key=m.item_id(case.text);neighbour_key=m.item_id(text)
                target=next(row for row in context['eligible'] if row[2]==target_key)
                state=next(state for state,box in target[5] if state[4]==p.FromMM(.8))
                original=m._state(text)
                seeds={target_key:SimpleNamespace(after=(p.FromMM(20),p.FromMM(18.8))+state[2:]),
                       neighbour_key:SimpleNamespace(after=original)}
                changes,failed=context['assign']({target_key,neighbour_key},priority=target_key,seeds=seeds)
                self.assertEqual(before,m.fingerprint(case.board,p))
                if displacement==0:
                    self.assertIn(neighbour_key,failed)
                else:
                    self.assertFalse(failed)
                    moved=next(change for change in changes if m.item_id(change.item)==neighbour_key)
                    movement=math.dist(moved.after[:2],original[:2])
                    self.assertGreater(movement,0)
                    self.assertLessEqual(movement,p.FromMM(displacement))
                    first,second=[change.box for change in changes]
                    self.assertFalse(m._inflate(first,p.FromMM(.2),p).Intersects(second))
                    self.assertTrue(all(not change.leader_path for change in changes))

    def test_failed_target_probe_never_returns_a_placeable_neighbour_as_target(self):
        import sys
        case=ownership.LabelOwnershipTests();case.setUp();case.fp.SetPosition(case.v(100,100))
        neighbour=case.other_part('R2',20,20);case.courtyard(neighbour)
        text=neighbour.Reference();text.SetVisible(True);text.SetLayer(p.F_SilkS)
        text.SetTextSize(case.v(1,1));text.SetTextThickness(p.FromMM(.15))
        text.SetPosition(case.v(20,18.2))
        contexts=[]
        class Prepared(Exception):pass
        def capture(frame,event,arg):
            if event=='call' and frame.f_code.co_name=='assign' and frame.f_back.f_code.co_name=='plan':
                contexts.append(dict(frame.f_back.f_locals));raise Prepared()
            return None
        previous=sys.gettrace();sys.settrace(capture)
        try:
            with self.assertRaises(Prepared):m.plan(case.board,p,dict(allowed_rotations=(0,)))
        finally:sys.settrace(previous)
        context=contexts[-1];target_key=m.item_id(case.text);neighbour_key=m.item_id(text)
        before=m.fingerprint(case.board,p)
        available,failed=context['assign']({neighbour_key})
        self.assertTrue(available);self.assertFalse(failed)
        proposal,failed=context['assign']({target_key,neighbour_key},priority=target_key,target_only=True)
        self.assertEqual(proposal,[]);self.assertEqual(failed,{target_key})
        self.assertEqual(m.fingerprint(case.board,p),before)

    def test_unverified_legacy_guide_blocks_association_without_being_deleted(self):
        def crosses_old_line(path):
            (ax,ay),(bx,by)=path
            if ay==by:return ay==19.1 and max(ax,bx)>=16 and min(ax,bx)<=24
            if not min(ay,by)<=19.1<=max(ay,by):return False
            x=ax+(bx-ax)*(19.1-ay)/(by-ay)
            return 16<=x<=24
        for legacy in (False,True):
            with self.subTest(legacy=legacy):
                case=ownership.LabelOwnershipTests();case.setUp()
                case.pad.SetSize(case.v(.4,.4));case.courtyard(case.fp)
                case.text.SetPosition(case.v(20,18.2))
                line=p.PCB_SHAPE(case.board);line.SetShape(p.SHAPE_T_SEGMENT)
                line.SetLayer(p.F_SilkS);line.SetWidth(p.FromMM(.08))
                line.SetStart(case.v(16,19.1));line.SetEnd(case.v(24,19.1));case.board.Add(line)
                group=None
                if legacy:
                    group=p.PCB_GROUP(case.board);group.SetName(m.GUIDE_PREFIX+m.item_id(case.text))
                    group.AddItem(line);case.board.Add(group)
                before=m.fingerprint(case.board,p);original=m._state(case.text)
                review=m.plan(case.board,p)
                self.assertEqual(review.stats['placed'],1)
                path=review.outcomes[0]['sightline_mm']
                self.assertEqual(len(path),2)
                if legacy:
                    self.assertTrue(review.changes)
                    self.assertNotEqual(review.changes[0].after[:2],original[:2])
                    self.assertFalse(crosses_old_line(path))
                else:
                    # Ordinary decorative silk is not automatically interpreted
                    # as a component association. It still clears actual ink.
                    self.assertFalse(review.changes)
                    self.assertTrue(crosses_old_line(path))
                self.assertEqual(before,m.fingerprint(case.board,p))
                tx=m.apply(case.board,p,review)
                self.assertIn(m.item_id(line),{m.item_id(obj) for obj in case.board.GetDrawings()})
                self.assertEqual((line.GetStart().x,line.GetStart().y),(p.FromMM(16),p.FromMM(19.1)))
                self.assertEqual((line.GetEnd().x,line.GetEnd().y),(p.FromMM(24),p.FromMM(19.1)))
                if legacy:
                    self.assertIn(m.item_id(group),{m.item_id(obj) for obj in case.board.Groups()})
                    self.assertEqual(line.GetParentGroupId().AsString(),m.item_id(group))
                    self.assertFalse(lifecycle.verified_group_ids(case.board,p))
                tx.undo();self.assertEqual(before,m.fingerprint(case.board,p))
