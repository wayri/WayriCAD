"""Native endpoint centering: existing contacts, custody and rejection cases."""
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
class CenteringTests(unittest.TestCase):
    def setUp(self):
        from trace_refiner_plugin import refiner
        self.r=refiner
        self.temp=tempfile.TemporaryDirectory(prefix='wayricad-center-test-')
        self.path=Path(self.temp.name)/'example.kicad_pcb'
        self.path.with_suffix('.kicad_pro').write_text('{}')
        self.board=api.BOARD();self.board.SetFileName(str(self.path))
        self.v=lambda x,y:api.VECTOR2I(api.FromMM(x),api.FromMM(y))
        self.net=api.NETINFO_ITEM(self.board,'SIGNAL',1);self.board.Add(self.net)
        for a,b in zip([(0,0),(10,0),(10,6),(0,6)],[(10,0),(10,6),(0,6),(0,0)]):
            edge=api.PCB_SHAPE(self.board);edge.SetShape(api.SHAPE_T_SEGMENT)
            edge.SetLayer(api.Edge_Cuts);edge.SetStart(self.v(*a));edge.SetEnd(self.v(*b));self.board.Add(edge)
        self.pad=self.make_pad((3,2),angle=37)
        self.far=self.make_pad((7,2.15))
        self.track=self.make_track((3,2.15),(7,2.15))
        api.SaveBoard(str(self.path),self.board)

    def tearDown(self):self.temp.cleanup()

    def make_pad(self,position,angle=0,shape=None,net=None,layer=None):
        fp=api.FOOTPRINT(self.board);fp.SetReference('J'+str(len(list(self.board.GetFootprints()))+1))
        fp.SetPosition(self.v(*position));self.board.Add(fp)
        pad=api.PAD(fp);pad.SetPosition(self.v(*position));pad.SetSize(self.v(.8,.6))
        pad.SetShape(api.PAD_SHAPE_RECT if shape is None else shape)
        pad.SetAttribute(api.PAD_ATTRIB_SMD);pad.SetLayerSet(pad.SMDMask())
        pad.SetOrientation(api.EDA_ANGLE(angle,api.DEGREES_T));pad.SetNet(net or self.net);fp.Add(pad)
        if layer is not None:
            layers=api.LSET();layers.AddLayer(layer);pad.SetLayerSet(layers)
        return pad

    def make_track(self,start,end,net=None):
        track=api.PCB_TRACK(self.board);track.SetStart(self.v(*start));track.SetEnd(self.v(*end))
        track.SetWidth(api.FromMM(.2));track.SetLayer(api.F_Cu);track.SetNet(net or self.net);self.board.Add(track)
        return track

    def plan(self,**settings):
        return self.r.propose(self.board,api,dict(scope='whole board',mode='center contacts',**settings))

    def test_rotated_rect_existing_contact_preview_is_read_only(self):
        before=self.r.snapshot(self.board,api);review=self.plan()
        self.assertEqual(len(review.changes),1)
        change=review.changes[0]
        self.assertEqual(change.after[0],tuple(self.v(3,2)))
        self.assertEqual(change.after[1],change.before[1])
        self.assertEqual(self.r.snapshot(self.board,api),before)
        # This valid correction adds length and is separate from shortening.
        self.assertLess(self.r.change_metrics(change,api)['shortening_mm'],0)
        self.assertEqual(change.originals,[self.track])

    def test_circle_oval_roundrect_contacts_and_via(self):
        for shape in (api.PAD_SHAPE_CIRCLE,api.PAD_SHAPE_OVAL,api.PAD_SHAPE_ROUNDRECT):
            with self.subTest(shape=shape):
                self.pad.SetShape(shape)
                self.assertEqual(self.plan().changes[0].after[0],tuple(self.v(3,2)))
        self.pad.GetParent().Remove(self.pad)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.7))
        via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
        via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        self.assertEqual(self.plan().changes[0].after[0],tuple(self.v(3,2)))
        self.assertEqual(tuple(via.GetPosition()),tuple(self.v(3,2)))

    def test_gap_different_net_and_layer_are_not_routed(self):
        self.track.SetStart(self.v(3,2.8))
        self.assertFalse(self.plan(max_center_shift=2).changes)
        self.track.SetStart(self.v(3,2.15))
        layers=api.LSET();layers.AddLayer(api.B_Cu);self.pad.SetLayerSet(layers)
        self.assertFalse(self.plan().changes)
        self.pad.SetLayerSet(self.pad.SMDMask())
        other=api.NETINFO_ITEM(self.board,'ZZ_OTHER',2);self.board.Add(other);self.pad.SetNet(other)
        self.assertFalse(self.plan().changes)

    def test_ambiguous_overlapping_pads_and_pad_via_are_preserved(self):
        second=self.make_pad((3,2.1));self.assertFalse(self.plan().changes)
        second.GetParent().Remove(second)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.7))
        via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
        via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        self.assertFalse(self.plan().changes)

    def test_already_centered_limits_and_validation(self):
        self.assertFalse(self.plan(max_center_shift=.1).changes)
        self.assertTrue(self.plan(max_center_shift=.15).changes)
        for limit in (0,-1,2.01,float('nan'),float('inf'),True,'1'):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError,'max_center_shift'):self.plan(max_center_shift=limit)
        self.track.SetStart(self.v(3,2));self.assertFalse(self.plan().changes)

    def test_both_ends_centered_without_moving_terminal_objects(self):
        self.far.SetPosition(self.v(7,2))
        pads=[(self.r.uid(p),tuple(p.GetPosition())) for fp in self.board.GetFootprints() for p in fp.Pads()]
        change=self.plan().changes[0]
        self.assertEqual(change.after,[tuple(self.v(3,2)),tuple(self.v(7,2))])
        self.assertEqual(pads,[(self.r.uid(p),tuple(p.GetPosition())) for fp in self.board.GetFootprints() for p in fp.Pads()])

    def test_same_terminal_zero_length_and_preview_cancellation(self):
        self.track.SetEnd(self.v(3,1.9))
        self.assertFalse(self.plan().changes)
        self.track.SetEnd(self.v(7,2.15))
        source=self.r.snapshot(self.board,api)
        with self.assertRaisesRegex(ValueError,'cancelled'):
            self.r.propose(self.board,api,dict(scope='whole board',mode='center contacts'),progress=lambda _:False)
        self.assertEqual(self.r.snapshot(self.board,api),source)

    def test_endpoint_junction_midsegment_and_arc_contacts_preserved(self):
        neighbour=self.make_track((3,2.15),(2,4));self.assertFalse(self.plan().changes)
        self.board.Remove(neighbour)
        neighbour=self.make_track((5,2.15),(5,4));self.assertFalse(self.plan().changes)
        self.board.Remove(neighbour)
        arc=api.PCB_ARC(self.board);arc.SetStart(self.v(3,2.15));arc.SetMid(self.v(2.5,2.65))
        arc.SetEnd(self.v(3,3.15));arc.SetWidth(api.FromMM(.2));arc.SetLayer(api.F_Cu);arc.SetNet(self.net)
        self.board.Add(arc);self.assertFalse(self.plan().changes)

    def test_pad_interior_contact_is_preserved(self):
        self.make_pad((5,2.15))
        self.assertFalse(self.plan().changes)

    def test_fixed_far_endpoint_route_continuation_is_preserved(self):
        next_track=self.make_track((7,2.15),(8,3))
        review=self.plan()
        self.assertEqual(len(review.changes),1)
        self.assertEqual(self.r.uid(review.changes[0].originals[0]),self.r.uid(self.track))
        self.assertEqual(self.r.point(next_track),tuple(self.v(7,2.15)))

    def test_offset_custom_locked_grouped_targets_and_tracks_preserved(self):
        self.pad.SetOffset(self.v(.1,0));self.assertFalse(self.plan().changes)
        self.pad.SetOffset(self.v(0,0));self.pad.SetShape(api.PAD_SHAPE_CUSTOM)
        self.assertFalse(self.plan().changes);self.pad.SetShape(api.PAD_SHAPE_RECT)
        for item in (self.track,self.pad,self.pad.GetParent()):
            item.SetLocked(True);self.assertFalse(self.plan().changes);item.SetLocked(False)
        group=api.PCB_GROUP(self.board);self.board.Add(group);group.AddItem(self.track)
        self.assertFalse(self.plan().changes);group.RemoveItem(self.track)
        group.AddItem(self.pad.GetParent());self.assertFalse(self.plan().changes)

    def test_modes_scopes_and_protected_or_tuned_nets(self):
        self.assertFalse(self.r.propose(self.board,api,dict(mode='center contacts')).changes)
        self.track.SetSelected();self.assertTrue(self.r.propose(self.board,api,dict(mode='center contacts')).changes)
        self.assertFalse(self.plan(layers=['B.Cu']).changes)
        self.net.SetNetname('USB_DATA');self.assertFalse(self.plan().changes)
        self.net.SetNetname('SIGNAL')
        self.path.with_suffix('.kicad_dru').write_text('(version 1) (rule "timing" (constraint length (max 10mm)))')
        with self.assertRaisesRegex(ValueError,'Custom length'):self.plan()

    def test_connected_tuning_chain_first_last_and_fragmented_are_preserved(self):
        points=[(3,2.15),(4,2.16),(5,2.15),(6,2.16),(7,2.15)]
        self.far.SetPosition(self.v(7,2))
        for fragmented in (False,True):
            with self.subTest(fragmented=fragmented):
                for track in list(self.board.GetTracks()):self.board.Remove(track)
                for a,b in zip(points,points[1:]):
                    vertices=[(a[0]+(b[0]-a[0])*i/4,a[1]+(b[1]-a[1])*i/4) for i in range(5)] if fragmented else [a,b]
                    for start,end in zip(vertices,vertices[1:]):self.make_track(start,end)
                review=self.plan()
                self.assertFalse(review.changes)
                self.assertTrue(any('Tuning' in reason for _,reason in review.skipped))

    def test_loop_and_inspection_budget_preserve_routing(self):
        for track in list(self.board.GetTracks()):self.board.Remove(track)
        for start,end in zip([(3,2.15),(4,2.15),(4,3),(3,3)],[(4,2.15),(4,3),(3,3),(3,2.15)]):
            self.make_track(start,end)
        self.assertFalse(self.plan().changes)
        with patch('trace_refiner_plugin.centering.time.monotonic',side_effect=[0,31]):
            review=self.plan()
        self.assertFalse(review.changes);self.assertIn('budget',review.skipped[0][1])

    def test_uuid_style_stale_digest_undo_and_idempotence(self):
        review=self.plan();before=self.r.snapshot(self.board,api)
        key=self.r.uid(self.track)
        review.validated=True;review.validation_digest=self.r.proposal_digest(review)
        mode=review.settings['mode'];review.settings['mode']='refine'
        with self.assertRaisesRegex(ValueError,'Proposal changed'):self.r.Transaction(self.board,api,review)
        review.settings['mode']=mode
        tx=self.r.Transaction(self.board,api,review).redo()
        self.assertFalse(self.plan().changes)
        centered=next(iter(self.board.GetTracks()))
        self.assertEqual(self.r.uid(centered),key);self.assertEqual(centered.GetWidth(),self.track.GetWidth())
        self.assertEqual(centered.GetNetCode(),self.track.GetNetCode());self.assertEqual(centered.GetLayer(),self.track.GetLayer())
        tx.undo();self.assertEqual(self.r.snapshot(self.board,api),before);tx.redo()
        centered=next(iter(self.board.GetTracks()));centered.SetWidth(api.FromMM(.3))
        with self.assertRaisesRegex(ValueError,'changed'):tx.undo()

    def test_detached_native_drc_and_partitions_preserved(self):
        review=self.plan();before=self.r.snapshot(self.board,api)
        terminals=self.r.connectivity(self.board,api)
        evidence=Path(self.temp.name)/'evidence'
        self.r.validate_detached(self.board,api,review,evidence_dir=evidence)
        self.assertEqual(review.evidence['new_findings'],0)
        self.assertEqual(self.r.snapshot(self.board,api),before)
        baseline=json.loads(next((evidence/'baseline').glob('drc.json')).read_text())
        affected={self.r.uid(self.track)}
        # Native fixture proves these existing off-centre contacts have no
        # affected-track warning. No guessed DRC exception is introduced.
        self.assertFalse([finding for kind in ('violations','unconnected_items')
                          for finding in baseline.get(kind,[])
                          if any(item.get('uuid') in affected for item in finding.get('items',[]))])
        tx=self.r.Transaction(self.board,api,review).redo()
        self.assertEqual(self.r.connectivity(self.board,api),terminals)
        tx.undo();self.assertEqual(self.r.snapshot(self.board,api),before)

    def test_edge_capsule_pad_and_via_contacts_are_already_connected(self):
        self.pad.SetOrientation(api.EDA_ANGLE(0,api.DEGREES_T));self.pad.SetSize(self.v(.6,.6))
        self.track.SetStart(self.v(3.35,2));self.track.SetEnd(self.v(7,2));self.far.SetPosition(self.v(7,2))
        for kind in ('pad','via'):
            with self.subTest(kind=kind):
                if kind=='via':
                    self.pad.GetParent().Remove(self.pad)
                    via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.6))
                    via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
                    via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
                before=self.r.snapshot(self.board,api);partitions=self.r.connectivity(self.board,api)
                # End centre is outside copper, but its .1mm-radius capsule
                # overlaps .05mm. KiCad 10 considers this an existing contact.
                self.assertEqual(len(partitions),1);self.assertEqual(len(partitions[0]),2)
                review=self.plan(max_center_shift=.5);self.assertEqual(len(review.changes),1)
                evidence=Path(self.temp.name)/('edge-'+kind)
                self.r.validate_detached(self.board,api,review,evidence_dir=evidence)
                for version in ('baseline','candidate'):
                    report=json.loads((evidence/version/'drc.json').read_text())
                    self.assertFalse([finding for category in ('violations','unconnected_items')
                                      for finding in report.get(category,[]) if any(
                                          item.get('uuid')==self.r.uid(self.track) for item in finding.get('items',[]))])
                tx=self.r.Transaction(self.board,api,review).redo()
                self.assertEqual(self.r.connectivity(self.board,api),partitions)
                tx.undo();self.assertEqual(self.r.snapshot(self.board,api),before)

    def test_existing_affected_track_short_still_blocks_centering(self):
        other=api.NETINFO_ITEM(self.board,'ZZ_OTHER',2);self.board.Add(other)
        crossing=self.make_track((5,1.5),(5,3),net=other)
        self.make_pad((5,3),net=other)
        api.SaveBoard(str(self.path),self.board)
        review=self.plan()
        self.assertEqual(crossing.GetNetname(),'ZZ_OTHER')
        self.assertEqual(len(review.changes),1)
        with self.assertRaisesRegex(ValueError,'already has native DRC findings'):
            self.r.validate_detached(self.board,api,review)
        self.assertFalse(review.validated)

    def test_native_via_warning_repaired_and_project_rules_preserved(self):
        self.pad.GetParent().Remove(self.pad)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.6))
        via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
        via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        self.board.GetDesignSettings().m_MinClearance=api.FromMM(.137)
        self.board.GetDesignSettings().m_TrackMinWidth=api.FromMM(.11)
        api.SaveBoard(str(self.path),self.board,True)
        project={'board':{'design_settings':{'rules':{'min_clearance':.137,'min_track_width':.11},
                   'rule_severities':{'track_not_centered_on_via':'ignore'}}}}
        self.path.with_suffix('.kicad_pro').write_text(json.dumps(project))
        source=self.path.with_suffix('.kicad_pro').read_bytes()
        review=self.plan();before=self.r.snapshot(self.board,api)
        evidence=Path(self.temp.name)/'via-evidence'
        self.r.validate_detached(self.board,api,review,evidence_dir=evidence)
        self.assertEqual(review.evidence['repaired_via_centers'],1)
        self.assertEqual(review.evidence['new_findings'],0)
        self.assertEqual(self.path.with_suffix('.kicad_pro').read_bytes(),source)
        self.assertEqual(self.r.snapshot(self.board,api),before)
        for version in ('baseline','candidate'):
            copied=json.loads(next((evidence/version).glob('*.kicad_pro')).read_text())
            rules=copied['board']['design_settings']
            self.assertEqual(rules['rules']['min_clearance'],.137)
            self.assertEqual(rules['rules']['min_track_width'],.11)
            self.assertEqual(rules['rule_severities']['track_not_centered_on_via'],'error')
            report=json.loads((evidence/version/'drc.json').read_text())
            warnings=[row for row in report['violations'] if row['type']=='track_not_centered_on_via']
            self.assertEqual(len(warnings),1 if version=='baseline' else 0)
        tx=self.r.Transaction(self.board,api,review).redo();tx.undo()
        self.assertEqual(self.r.snapshot(self.board,api),before)

    def test_via_warning_exception_rejects_wrong_target_net_layer_shift_or_mode(self):
        from trace_refiner_plugin.centering import repairs_via_finding
        self.pad.GetParent().Remove(self.pad)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.6))
        via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
        via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        review=self.plan()
        finding=dict(type='track_not_centered_on_via',items=[dict(uuid=self.r.uid(self.track)),dict(uuid=self.r.uid(via))])
        self.assertTrue(repairs_via_finding(finding,review.changes,self.board,api,.25))
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.1))
        other=api.NETINFO_ITEM(self.board,'ZZ_OTHER',2);self.board.Add(other)
        via.SetNet(other)
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.25))
        via.SetNet(self.net);via.SetViaType(api.VIATYPE_BLIND);via.SetLayerPair(api.In1_Cu,api.B_Cu)
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.25))
        via.SetViaType(api.VIATYPE_THROUGH);via.SetLayerPair(api.F_Cu,api.B_Cu)
        finding['type']='track_dangling'
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.25))
        finding['type']='track_not_centered_on_via'
        finding['items'][1]['uuid']=self.r.uid(self.far)
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.25))
        finding['items'][1]['uuid']=self.r.uid(via)
        review.changes[0].after[0]=review.changes[0].before[0]
        self.assertFalse(repairs_via_finding(finding,review.changes,self.board,api,.25))
        review=self.plan();review.settings['mode']='refine'
        project={'board':{'design_settings':{'rule_severities':{'track_not_centered_on_via':'error'}}}}
        self.path.with_suffix('.kicad_pro').write_text(json.dumps(project))
        review.rules=self.r.rule_hash(self.board)
        with self.assertRaisesRegex(ValueError,'already has native DRC findings'):
            self.r.validate_detached(self.board,api,review)

    def test_unrepaired_via_warning_still_blocks_centering(self):
        self.pad.GetParent().Remove(self.pad)
        via=api.PCB_VIA(self.board);via.SetPosition(self.v(3,2));via.SetWidth(api.FromMM(.6))
        via.SetDrill(api.FromMM(.3));via.SetViaType(api.VIATYPE_THROUGH)
        via.SetLayerPair(api.F_Cu,api.B_Cu);via.SetNet(self.net);self.board.Add(via)
        review=self.plan();review.changes[0].after[0]=review.changes[0].before[0]
        with self.assertRaisesRegex(ValueError,'already has native DRC findings'):
            self.r.validate_detached(self.board,api,review)


if __name__=='__main__':unittest.main()
