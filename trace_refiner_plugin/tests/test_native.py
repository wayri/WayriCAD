"""Native copper custody, scope and independent KiCad DRC acceptance checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import pcbnew as api
except ImportError:
    api=None


@unittest.skipIf(api is None,'KiCad native Python required')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='refiner-test-');self.path=Path(self.temp.name)/'example.kicad_pcb'
        self.path.with_suffix('.kicad_pro').write_text('{}')
        self.board=api.BOARD();self.board.SetFileName(str(self.path));self.v=lambda x,y:api.VECTOR2I(api.FromMM(x),api.FromMM(y))
        for a,b in zip([(0,0),(10,0),(10,5),(0,5)],[(10,0),(10,5),(0,5),(0,0)]):
            edge=api.PCB_SHAPE(self.board);edge.SetShape(api.SHAPE_T_SEGMENT);edge.SetLayer(api.Edge_Cuts);edge.SetStart(self.v(*a));edge.SetEnd(self.v(*b));self.board.Add(edge)
        self.net=api.NETINFO_ITEM(self.board,'SIGNAL',1);self.board.Add(self.net)
        self.points=[(1,2),(3,2),(3.03,2.03),(5,2.03),(5.03,2),(7,2)]
        self.tracks=[]
        for a,b in zip(self.points,self.points[1:]):self.tracks.append(self.track(a,b))
        for i,p in enumerate((self.points[0],self.points[-1])):
            fp=api.FOOTPRINT(self.board);fp.SetReference('J'+str(i+1));fp.SetPosition(self.v(*p));self.board.Add(fp)
            pad=api.PAD(fp);pad.SetPosition(self.v(*p));pad.SetSize(self.v(.6,.6));pad.SetShape(api.PAD_SHAPE_RECT);pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());pad.SetNet(self.net);fp.Add(pad)
        api.SaveBoard(str(self.path),self.board)
    def track(self,a,b):
        t=api.PCB_TRACK(self.board);t.SetStart(self.v(*a));t.SetEnd(self.v(*b));t.SetLayer(api.F_Cu);t.SetWidth(api.FromMM(.2));t.SetNet(self.net);self.board.Add(t);return t
    def tearDown(self):self.temp.cleanup()
    def plan(self,**settings):
        from trace_refiner_plugin.refiner import propose
        return propose(self.board,api,dict(scope='whole board',**settings))
    def test_preview_is_read_only_and_endpoints_preserved(self):
        from trace_refiner_plugin.refiner import snapshot
        before=snapshot(self.board,api);plan=self.plan()
        self.assertEqual(len(plan.changes),1);c=plan.changes[0]
        self.assertEqual(c.before[0],c.after[0]);self.assertEqual(c.before[-1],c.after[-1])
        self.assertEqual(len(c.after),2);self.assertEqual(snapshot(self.board,api),before)
    def test_selected_track_and_net_scope_layer_and_filters(self):
        from trace_refiner_plugin.refiner import propose
        self.assertFalse(propose(self.board,api).changes)
        for t in self.tracks:t.SetSelected()
        self.assertTrue(propose(self.board,api).changes)
        self.assertTrue(propose(self.board,api,dict(scope='selected nets')).changes)
        self.assertFalse(self.plan(layers=['B.Cu']).changes)
        self.assertTrue(propose(self.board,api,dict(scope='net filters',nets=['SIGNAL'])).changes)
        self.assertTrue(propose(self.board,api,dict(scope='groups',groups=['Default'])).changes)
    def test_locked_grouped_differential_and_custom_rules_preserved(self):
        for t in self.tracks:t.SetLocked(True)
        self.assertFalse(self.plan().changes)
        for t in self.tracks:t.SetLocked(False)
        self.net.SetNetname('PAIR_P');self.assertFalse(self.plan().changes)
        self.net.SetNetname('SIGNAL')
        self.path.with_suffix('.kicad_dru').write_text("(version 1) (rule \"tuned\" (constraint length (max 10mm)))")
        with self.assertRaisesRegex(ValueError,'Custom length'):self.plan()
    def test_branch_connection_preserved(self):
        self.track((3.03,2.03),(3.03,4))
        plan=self.plan()
        for c in plan.changes:
            self.assertNotIn((api.FromMM(3.03),api.FromMM(2.03)),c.before[1:-1])
    def test_first_segment_midpoint_contact_and_vias_preserved(self):
        self.track((2,2),(2,3.5))
        self.assertFalse(self.plan().changes)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(8,4));via.SetWidth(api.FromMM(.6));via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH);via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        self.assertFalse(self.plan().changes)
    def test_pad_only_net_is_in_rule_fingerprint(self):
        from trace_refiner_plugin.refiner import native_rules
        net=api.NETINFO_ITEM(self.board,'PAD_ONLY',2);self.board.Add(net)
        fp=next(iter(self.board.GetFootprints()));pad=api.PAD(fp);pad.SetPosition(self.v(9,3));pad.SetSize(self.v(.5,.5));pad.SetNet(net);fp.Add(pad)
        self.assertIn('PAD_ONLY',dict(native_rules(self.board)['netclasses']))
    def test_first_segment_interior_pad_contact_is_preserved(self):
        fp=next(iter(self.board.GetFootprints()));pad=api.PAD(fp)
        pad.SetPosition(self.v(2,2));pad.SetSize(self.v(.2,.2));pad.SetShape(api.PAD_SHAPE_RECT);pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask());pad.SetNet(self.net);fp.Add(pad)
        self.assertFalse(self.plan().changes)
    def test_native_validation_apply_undo_redo_and_stale_rejection(self):
        from trace_refiner_plugin.refiner import validate,Transaction,snapshot,connectivity
        review=self.plan();before=snapshot(self.board,api);terminals=connectivity(self.board,api)
        with self.assertRaisesRegex(ValueError,'Validate'):Transaction(self.board,api,review)
        validate(self.board,api,review)
        self.assertTrue(review.validated);self.assertEqual(review.evidence['new_findings'],0)
        tx=Transaction(self.board,api,review).redo()
        self.assertEqual(connectivity(self.board,api),terminals);self.assertLess(len(list(self.board.GetTracks())),len(self.tracks))
        tx.undo();self.assertEqual(snapshot(self.board,api),before);tx.redo()
        next(iter(self.board.GetTracks())).SetWidth(api.FromMM(.3))
        with self.assertRaisesRegex(ValueError,'changed'):tx.undo()
    def test_clearance_collision_blocks_apply(self):
        from trace_refiner_plugin.refiner import validate
        # A narrow obstacle is legal beside the jog but blocks its straight shortcut.
        other=api.NETINFO_ITEM(self.board,'OBSTACLE',2);self.board.Add(other)
        obstacle=self.track((4,1.70),(4.5,1.70));obstacle.SetNet(other);obstacle.SetWidth(api.FromMM(.2))
        project={'board':{'design_settings':{'rules':{'min_clearance':.12}}}}
        self.path.with_suffix('.kicad_pro').write_text(json.dumps(project))
        self.board.GetDesignSettings().m_MinClearance=api.FromMM(.12)
        review=self.plan()
        with self.assertRaisesRegex(ValueError,'DRC|findings'):validate(self.board,api,review)
        self.assertFalse(review.validated)
    def test_partial_mutation_failure_recovers(self):
        from trace_refiner_plugin.refiner import Transaction,snapshot,proposal_digest
        review=self.plan();review.validated=True;review.validation_digest=proposal_digest(review);before=snapshot(self.board,api);original=self.board.Add
        count=[0]
        def fail_once(item):
            count[0]+=1
            if count[0]==1:raise RuntimeError('Injected native failure')
            return original(item)
        with patch.object(self.board,'Add',side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError,'Injected'):Transaction(self.board,api,review).redo()
        self.assertEqual(snapshot(self.board,api),before)
    def test_live_rules_stale_and_unsaved_rules_block_validation(self):
        from trace_refiner_plugin.refiner import snapshot,validate_detached
        review=self.plan();source=snapshot(self.board,api)
        self.board.GetDesignSettings().m_MinClearance=api.FromMM(.9)
        self.assertNotEqual(snapshot(self.board,api),source)
        with self.assertRaisesRegex(ValueError,'changed'):validate_detached(self.board,api,review)
        review=self.plan()
        with self.assertRaisesRegex(ValueError,'Board Setup'):validate_detached(self.board,api,review)
    def test_post_exchange_snapshot_failure_recovers(self):
        from trace_refiner_plugin.refiner import Transaction,snapshot,proposal_digest
        review=self.plan();review.validated=True;review.validation_digest=proposal_digest(review);before=snapshot(self.board,api)
        count=[0]
        def fail_after_exchange(board,native):
            count[0]+=1
            if count[0]==2:raise OSError('Injected temporary storage failure')
            return snapshot(board,native)
        with patch('trace_refiner_plugin.refiner.snapshot',side_effect=fail_after_exchange):
            with self.assertRaisesRegex(OSError,'temporary storage'):Transaction(self.board,api,review).redo()
        self.assertEqual(snapshot(self.board,api),before)
    def test_bus_net_filter_is_literal(self):
        from trace_refiner_plugin.refiner import propose
        self.net.SetNetname('DATA[0]')
        self.assertTrue(propose(self.board,api,dict(scope='net filters',nets=['DATA[0]'])).changes)
        self.assertFalse(propose(self.board,api,dict(scope='net filters',nets=['DATA0'])).changes)
    def test_ignored_clearance_is_enabled_for_candidate_gate(self):
        from trace_refiner_plugin.refiner import validate_detached
        other=api.NETINFO_ITEM(self.board,'OBSTACLE',2);self.board.Add(other)
        obstacle=self.track((4,1.70),(4.5,1.70));obstacle.SetNet(other)
        self.board.GetDesignSettings().m_MinClearance=api.FromMM(.12)
        project={'board':{'design_settings':{'rules':{'min_clearance':.12},'rule_severities':{'clearance':'ignore'}}}}
        self.path.with_suffix('.kicad_pro').write_text(json.dumps(project))
        review=self.plan()
        with self.assertRaisesRegex(ValueError,'DRC|findings'):validate_detached(self.board,api,review)
        self.assertEqual(json.loads(self.path.with_suffix('.kicad_pro').read_text()),project)

    def test_long_fragmented_chain_is_refined_with_fixed_terminals(self):
        from trace_refiner_plugin.refiner import validate_detached,Transaction,snapshot,connectivity
        for item in self.tracks:self.board.Remove(item)
        points=[(1,2)]+[(2+4*i/400,2) for i in range(401)]+[(7,2)]
        self.tracks=[self.track(a,b) for a,b in zip(points,points[1:])]
        before=snapshot(self.board,api);partitions=connectivity(self.board,api)
        review=self.plan();self.assertEqual(len(review.changes),1)
        self.assertEqual(len(review.changes[0].originals),402)
        self.assertEqual(len(review.changes[0].after),2)
        validate_detached(self.board,api,review)
        tx=Transaction(self.board,api,review).redo()
        self.assertEqual(connectivity(self.board,api),partitions)
        tx.undo();self.assertEqual(snapshot(self.board,api),before)

    def test_chain_over_work_cap_is_preserved_as_one_unit(self):
        for item in self.tracks:self.board.Remove(item)
        for fp in list(self.board.GetFootprints()):self.board.Remove(fp)
        for i in range(2050):self.track((1+6*i/2050,2),(1+6*(i+1)/2050,2))
        review=self.plan();self.assertFalse(review.changes)
        self.assertEqual(len(review.skipped),1)
        self.assertIn('Long chain',review.skipped[0][1])

    def test_validation_is_bound_to_proposal_and_replacement_geometry(self):
        from trace_refiner_plugin.refiner import validate,Transaction,snapshot,subset_plan
        review=self.plan();validate(self.board,api,review);before=snapshot(self.board,api)
        change=review.changes[0];after=change.after[:]
        change.after[-1]=(change.after[-1][0]+10,change.after[-1][1])
        with self.assertRaisesRegex(ValueError,'Proposal changed'):Transaction(self.board,api,review)
        change.after=after
        forged=change.originals[0].Duplicate();forged.SetStart(api.VECTOR2I(*after[0]));forged.SetEnd(api.VECTOR2I(*after[-1]));forged.SetWidth(api.FromMM(.3))
        change.added=[forged]
        with self.assertRaisesRegex(ValueError,'Replacement track'):Transaction(self.board,api,review).redo()
        self.assertEqual(snapshot(self.board,api),before)
        subset=subset_plan(review,[0]);self.assertFalse(subset.validated);self.assertFalse(subset.validation_digest)
        with self.assertRaisesRegex(ValueError,'Validate'):Transaction(self.board,api,subset)

    def test_post_mutation_add_and_remove_failures_restore_source(self):
        from trace_refiner_plugin.refiner import Transaction,snapshot,proposal_digest
        for operation in ('Add','Remove'):
            review=self.plan();review.validated=True;review.validation_digest=proposal_digest(review)
            before=snapshot(self.board,api);original=getattr(self.board,operation);calls=[0]
            def failing(item):
                original(item);calls[0]+=1
                if calls[0]==1:raise RuntimeError('Injected after mutation')
            with patch.object(self.board,operation,side_effect=failing):
                with self.assertRaisesRegex(RuntimeError,'after mutation'):Transaction(self.board,api,review).redo()
            self.assertEqual(snapshot(self.board,api),before)

    def test_snapshot_uses_no_temporary_board_save(self):
        from trace_refiner_plugin.refiner import snapshot
        before=self.board.GetFileName()
        with patch.object(api,'SaveBoard',side_effect=AssertionError('Snapshot wrote a file')):
            self.assertEqual(snapshot(self.board,api),snapshot(self.board,api))
        self.assertEqual(self.board.GetFileName(),before)

    def test_copper_index_matches_brute_force_native_bounds(self):
        from trace_refiner_plugin.refiner import _CopperIndex,uid
        for i in range(30):self.track((i-15,-i/2),(i-14,1-i/2))
        rows=list(self.board.GetTracks());index=_CopperIndex(rows,[api.F_Cu,api.B_Cu],api)
        for x in range(-20,22,3):
            values=[api.FromMM(v) for v in (x,-10,x+4,10)]
            left,top,right,bottom=values
            expected={uid(t) for t in rows if not (t.GetBoundingBox().GetRight()<left or t.GetBoundingBox().GetLeft()>right or t.GetBoundingBox().GetBottom()<top or t.GetBoundingBox().GetTop()>bottom)}
            self.assertEqual({uid(t) for t in index.query(1,api.F_Cu,values)},expected)
            self.assertFalse(index.query(1,api.B_Cu,values))

    def test_invalid_settings_are_actionable(self):
        from trace_refiner_plugin.refiner import propose
        for settings in (dict(max_deviation=True),dict(max_deviation='0.1'),dict(protected=[]),dict(nets='SIGNAL'),dict(unknown=1)):
            with self.assertRaises(ValueError):propose(self.board,api,settings)

    def test_mask_boundaries_and_real_groups_are_protected(self):
        first=self.tracks[0];first.SetHasSolderMask(True);first.SetLocalSolderMaskMargin(api.FromMM(.1))
        review=self.plan()
        self.assertTrue(all(len({(t.HasSolderMask(),t.GetLocalSolderMaskMargin()) for t in c.originals})==1 for c in review.changes))
        self.assertTrue(all(first not in c.originals for c in review.changes))
        group=api.PCB_GROUP(self.board);group.SetName('Protected routing');self.board.Add(group)
        for track in self.tracks:group.AddItem(track)
        self.assertFalse(self.plan().changes)

    def test_via_and_other_layer_routing_survive_real_refinement(self):
        from trace_refiner_plugin.refiner import validate_detached,Transaction,connectivity,uid
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(1,2));via.SetWidth(api.FromMM(.6));via.SetDrill(api.FromMM(.3))
        via.SetViaType(api.VIATYPE_THROUGH);via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        bottom=self.track((1,2),(9,2.03));bottom.SetLayer(api.B_Cu)
        fp=api.FOOTPRINT(self.board);fp.SetReference('J3');fp.SetPosition(self.v(9,2.03));self.board.Add(fp)
        pad=api.PAD(fp);pad.SetPosition(self.v(9,2.03));pad.SetSize(self.v(.6,.6));pad.SetShape(api.PAD_SHAPE_RECT)
        pad.SetAttribute(api.PAD_ATTRIB_SMD);mask=api.LSET();mask.AddLayer(api.B_Cu);mask.AddLayer(api.B_Mask);pad.SetLayerSet(mask);pad.SetNet(self.net);fp.Add(pad)
        before=connectivity(self.board,api);original=(uid(via),via.GetPosition().x,via.GetPosition().y,via.GetDrill(),tuple(via.GetLayerSet().Seq()))
        review=self.plan();self.assertTrue(review.changes)
        self.assertTrue(all(c.layer==api.F_Cu for c in review.changes))
        validate_detached(self.board,api,review);Transaction(self.board,api,review).redo()
        self.assertEqual(before,connectivity(self.board,api))
        self.assertEqual(original,(uid(via),via.GetPosition().x,via.GetPosition().y,via.GetDrill(),tuple(via.GetLayerSet().Seq())))
        self.assertIn(uid(bottom),{uid(t) for t in self.board.GetTracks()})


if __name__=='__main__':unittest.main()
