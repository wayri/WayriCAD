"""Routing regressions; native cases run with KiCad's bundled Python."""
import unittest
from wayricad_runtime.geometry import (positive, disk_inside, segment_segment_distance, board_fingerprint)
from wayricad_runtime.operations import add_group, remove_group, RecoveryError
from wayricad_runtime.routing import plan_fanout, plan_stitching, fanout_items, plan_document
try:
    import pcbnew
except ImportError:
    pcbnew = None


class GeometryTests(unittest.TestCase):
    def test_reject_nonfinite_dimensions(self):
        for value in (-1, 0, float('nan'), float('inf')):
            with self.assertRaises(ValueError): positive(value, 'Dimension')

    def test_crossing_track_segments(self):
        self.assertEqual(segment_segment_distance((0,0),(2,2),(0,2),(2,0)),0)
        self.assertEqual(segment_segment_distance((0,0),(1,0),(2,0),(3,0)),1)

    def test_disk_respects_holes_and_edge_radius(self):
        square=[(0,0),(10,0),(10,10),(0,10)]
        hole=[(4,4),(6,4),(6,6),(4,6)]
        self.assertFalse(disk_inside((.2,5),.3,square))
        self.assertFalse(disk_inside((5,5),.3,square,[hole]))
        self.assertTrue(disk_inside((2,2),.3,square,[hole]))


class FakeGroup:
    def __init__(self, board=None): self.items=[]; self.name=''
    def SetName(self,name):self.name=name
    def GetName(self):return self.name
    def AddItem(self,item):self.items.append(item)
    def RemoveItem(self,item):self.items.remove(item)


class FakeBoard:
    def __init__(self):self.items=[];self.fail_add=None;self.fail_remove=None
    def Add(self,item):
        if item is self.fail_add:raise RuntimeError('add failed')
        self.items.append(item)
    def Remove(self,item):
        if item is self.fail_remove:raise RuntimeError('remove failed')
        self.items.remove(item)


class RecoveryTests(unittest.TestCase):
    def test_partial_add_rolls_back(self):
        board=FakeBoard();a,b=object(),object();board.fail_add=b
        with self.assertRaises(RuntimeError):add_group(board,[a,b],'Test',FakeGroup)
        self.assertEqual(board.items,[])

    def test_partial_undo_restores_membership(self):
        board=FakeBoard();a,b=object(),object();group=add_group(board,[a,b],'Test',FakeGroup)
        board.fail_remove=b
        with self.assertRaises(RuntimeError):remove_group(board,group,[a,b])
        self.assertCountEqual(board.items,[a,b,group])
        self.assertCountEqual(group.items,[a,b])

    def test_failed_rollback_preserves_references(self):
        board=FakeBoard();a,b=object(),object();board.fail_add=b;board.fail_remove=a
        with self.assertRaises(RecoveryError) as caught:add_group(board,[a,b],'Test',FakeGroup)
        self.assertIn(a,caught.exception.items)


@unittest.skipIf(pcbnew is None, 'KiCad native Python required')
class NativeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.board=pcbnew.BOARD()
        self.ground=pcbnew.NETINFO_ITEM(self.board,'GND');self.board.Add(self.ground)
        self.signal=pcbnew.NETINFO_ITEM(self.board,'SIGNAL');self.board.Add(self.signal)
        for a,b in (((0,0),(20,0)),((20,0),(20,20)),((20,20),(0,20)),((0,20),(0,0))):
            line=pcbnew.PCB_SHAPE(self.board);line.SetShape(pcbnew.SHAPE_T_SEGMENT)
            line.SetStart(self.pos(*a));line.SetEnd(self.pos(*b));line.SetLayer(pcbnew.Edge_Cuts)
            self.board.Add(line)

    @staticmethod
    def pos(x,y):return pcbnew.VECTOR2I(pcbnew.FromMM(x),pcbnew.FromMM(y))

    def pad(self,ref,x,y,net=None,smd=True):
        fp=pcbnew.FOOTPRINT(self.board);fp.SetReference(ref);fp.SetPosition(self.pos(x,y));self.board.Add(fp)
        pad=pcbnew.PAD(fp);pad.SetNumber('1');pad.SetPosition(self.pos(x,y));pad.SetSize(self.pos(.5,.5))
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD if smd else pcbnew.PAD_ATTRIB_PTH)
        layers=pcbnew.LSET();layers.AddLayer(pcbnew.F_Cu);pad.SetLayerSet(layers);pad.SetNet(net or self.ground);fp.Add(pad)
        return fp,pad

    def test_fanout_only_smd_and_no_plan_mutation(self):
        self.pad('U1',5,5);self.pad('J1',10,10,smd=False)
        before=board_fingerprint(self.board)
        plans,rejected=plan_fanout(self.board,pcbnew)
        self.assertEqual(len(plans),1);self.assertEqual(plans[0].footprint.GetReference(),'U1')
        self.assertEqual(board_fingerprint(self.board),before)
        items=fanout_items(self.board,pcbnew,plans)
        self.assertEqual(len(items),2);self.assertEqual(len(self.board.GetTracks()),0)
        group=add_group(self.board,items,'WayriCAD Fanout Test',pcbnew.PCB_GROUP)
        self.assertEqual(len(self.board.GetTracks()),2)
        remove_group(self.board,group,items)
        self.assertEqual(len(self.board.GetTracks()),0)
        group=add_group(self.board,items,'WayriCAD Fanout Redo',pcbnew.PCB_GROUP)
        self.assertEqual(len(self.board.GetTracks()),2)

    def test_negative_dimensions_and_bad_drill_rejected(self):
        for settings in ({'width':-1},{'length':0},{'via_drill':1},{'offset_x':float('nan')}):
            with self.assertRaises(ValueError):plan_fanout(self.board,pcbnew,settings)

    def test_fanout_obstacle_and_edge_rejections(self):
        self.pad('U1',5,5);self.pad('U2',6,5,self.signal)
        plans,rejected=plan_fanout(self.board,pcbnew,{'scope':'Reference wildcard','ref':'U1'})
        self.assertEqual(plans,[]);self.assertTrue(rejected)
        self.pad('U3',19,15)
        plans,rejected=plan_fanout(self.board,pcbnew,{'scope':'Reference wildcard','ref':'U3'})
        self.assertEqual(plans,[]);self.assertIn('edge',rejected[0])

    def test_stale_snapshot_catches_pad_size_and_net(self):
        fp,pad=self.pad('U1',5,5)
        initial=board_fingerprint(self.board);pad.SetSize(self.pos(.6,.5))
        self.assertNotEqual(initial,board_fingerprint(self.board))
        initial=board_fingerprint(self.board);pad.SetNet(self.signal)
        self.assertNotEqual(initial,board_fingerprint(self.board))

    def test_stitching_requires_target_zone(self):
        with self.assertRaisesRegex(ValueError,'No copper zones'):plan_stitching(self.board,pcbnew)

    def test_stitching_excluded_reference_is_local(self):
        self.pad('U1',5,5)
        settings={'require_target_zone':False,'skip_parts':False,'skip_refs':'U1'}
        vias,rejected=plan_stitching(self.board,pcbnew,settings)
        self.assertGreater(len(vias),10);self.assertEqual(len(self.board.GetTracks()),0)
        self.assertTrue(all(0<pcbnew.ToMM(v.GetPosition().x)<20 for v in vias))
        doc=plan_document('stitching',self.board,pcbnew,settings)
        self.assertEqual(len(doc['candidates']),len(vias))

    def test_cli_review_apply_and_stale_plan(self):
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from wayricad_runtime.cli import execute
        self.pad('U1',5,5)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'source.kicad_pcb';review=folder/'plan.json'
            svg=folder/'preview.svg';output=folder/'routed.kicad_pcb'
            self.assertTrue(pcbnew.SaveBoard(str(source),self.board))
            original=source.read_bytes()
            result=execute(SimpleNamespace(kind='fanout',operation='plan',board=str(source),settings=None,output=str(review),svg=str(svg)))
            self.assertEqual(result['accepted'],1);self.assertTrue(svg.exists())
            args=SimpleNamespace(kind='fanout',operation='apply',board=str(source),plan=str(review),output=str(output))
            result=execute(args);self.assertEqual(result['created_items'],2)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(len(pcbnew.LoadBoard(str(output)).GetTracks()),2)
            with self.assertRaisesRegex(ValueError,'new output'):execute(args)
            document=json.loads(review.read_text());document['candidates'][0]['end_mm'][0]+=1
            review.write_text(json.dumps(document));args.output=str(folder/'tampered.kicad_pcb')
            with self.assertRaisesRegex(ValueError,'changed'):execute(args)

    def test_layer_change_connects_source_pad_with_via(self):
        self.pad('U1',5,5)
        plans,_=plan_fanout(self.board,pcbnew,{'escape_layer':'B.Cu','pattern':'Radial outward','add_vias':False})
        self.assertEqual(len(plans),1);self.assertTrue(plans[0].start_via)
        self.assertEqual(plans[0].layer,pcbnew.B_Cu)
        items=fanout_items(self.board,pcbnew,plans)
        self.assertEqual(len(items),2)
        self.assertEqual(items[0].GetLayer(),pcbnew.B_Cu)
        self.assertEqual(items[1].GetPosition(),plans[0].start)

    def test_explicit_via_in_pad_mode(self):
        self.pad('U1',5,5)
        plans,_=plan_fanout(self.board,pcbnew,{'output_mode':'Via-in-pad','pattern':'Radial outward'})
        self.assertEqual(len(plans),1);self.assertFalse(plans[0].add_track)
        self.assertEqual(plans[0].start,plans[0].end)
        self.assertEqual(len(fanout_items(self.board,pcbnew,plans)),1)

    def test_project_netclass_assignment_and_pattern_filters(self):
        import json,tempfile
        from pathlib import Path
        from wayricad_runtime.routing import netclass_names
        self.pad('U1',5,5);self.pad('U2',10,10,self.signal)
        with tempfile.TemporaryDirectory() as directory:
            board_path=Path(directory)/'test.kicad_pcb';self.board.SetFileName(str(board_path))
            board_path.with_suffix('.kicad_pro').write_text(json.dumps({'net_settings':{
                'classes':[{'name':'Power'},{'name':'Logic'}],
                'netclass_assignments':{'GND':['Power']},
                'netclass_patterns':[{'netclass':'Logic','pattern':'SIG*'}]}}))
            self.assertIn('Power',netclass_names(self.board))
            plans,_=plan_fanout(self.board,pcbnew,{'netclass_filter':'Power'})
            self.assertEqual([p.pad.GetNetname() for p in plans],['GND'])
            plans,_=plan_fanout(self.board,pcbnew,{'netclass_filter':'Logic'})
            self.assertEqual([p.pad.GetNetname() for p in plans],['SIGNAL'])
            plans,_=plan_fanout(self.board,pcbnew,{'netclass_filter':'Default'})
            self.assertEqual(plans,[])

    def test_dense_grid_rejects_overlapping_vias(self):
        with self.assertRaisesRegex(ValueError,'Spacing'):
            plan_stitching(self.board,pcbnew,{'spacing':1,'density':'Dense selected area'})

if __name__=='__main__':unittest.main()
