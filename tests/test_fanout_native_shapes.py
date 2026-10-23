"""Native narrow-phase checks for dense pad fields and polygon keepouts."""
import unittest
import test_advanced_fanout as fixture
from wayricad_runtime.routing import FanoutPlanner
from wayricad_runtime.geometry import segment_hits_native

p=fixture.pcbnew


@unittest.skipIf(p is None,'Native KiCad required')
class NativeShapeTests(unittest.TestCase):
    setUp=fixture.AdvancedFanoutTests.setUp
    pos=staticmethod(fixture.AdvancedFanoutTests.pos)
    pad=fixture.AdvancedFanoutTests.pad

    def test_circle_corner_and_diagonal_track_are_not_solid_rectangles(self):
        pad=self.pad('BLOCK',20,20);pad.SetShape(p.PAD_SHAPE_CIRCLE);pad.SetSize(self.pos(.4,.4))
        planner=FanoutPlanner(self.board,p,{})
        point=self.pos(20.4,20.4)
        self.assertFalse(planner._copper_hits(pad,p.F_Cu,point,point,p.FromMM(.277)))
        self.assertTrue(planner._copper_hits(pad,p.F_Cu,self.pos(20.3,20),self.pos(20.3,20),p.FromMM(.277)))
        track=p.PCB_TRACK(self.board);track.SetStart(self.pos(18,18));track.SetEnd(self.pos(22,22));track.SetWidth(p.FromMM(.1));track.SetLayer(p.F_Cu)
        self.assertFalse(planner._copper_hits(track,p.F_Cu,self.pos(18,22),self.pos(18,22),p.FromMM(.1)))
        self.assertTrue(planner._copper_hits(track,p.F_Cu,self.pos(20,20),self.pos(20,20),p.FromMM(.1)))

    def test_polygon_hole_concavity_and_clearance(self):
        shape=p.SHAPE_POLY_SET();shape.NewOutline()
        for xy in ((10,10),(30,10),(30,30),(10,30)):shape.Append(self.pos(*xy))
        shape.NewHole()
        for xy in ((15,15),(15,25),(25,25),(25,15)):shape.Append(self.pos(*xy),0,0)
        for api in (p,None):
            self.assertFalse(segment_hits_native(self.pos(18,20),self.pos(22,20),p.FromMM(1),shape,api))
            self.assertTrue(segment_hits_native(self.pos(14,20),self.pos(22,20),0,shape,api))
            self.assertTrue(segment_hits_native(self.pos(15.5,20),self.pos(22,20),p.FromMM(.6),shape,api))

    def test_pour_refills_but_rule_area_stays_blocked(self):
        pad=self.pad('SIGNAL',22,20)
        planner=FanoutPlanner(self.board,p,dict(pattern='Radial outward',add_vias=False,width=.15,clearance=.1,length=1))
        zone=p.ZONE(self.board);zone.SetLayer(p.F_Cu)
        poly=zone.Outline();poly.NewOutline()
        for xy in ((21,19),(24,19),(24,21),(21,21)):poly.Append(self.pos(*xy))
        zone.SetFilledPolysList(p.F_Cu,poly);self.board.Add(zone)
        self.assertEqual(len(planner._plan()),1)
        zone.SetIsRuleArea(True);zone.SetDoNotAllowTracks(True)
        self.assertFalse(planner._plan());self.assertIn('zone/keepout',planner.plan_rejections[0])

    def test_reused_planner_does_not_keep_shapes_after_board_edit(self):
        self.pad('SIGNAL',22,20)
        blocker=self.pad('BLOCK',23,21)
        planner=FanoutPlanner(self.board,p,dict(pattern='Radial outward',net_filter='SIGNAL',add_vias=False,width=.15,clearance=.1,length=1))
        self.assertEqual(len(planner._plan()),1)
        blocker.SetPosition(self.pos(23,20))
        self.assertFalse(planner._plan());self.assertIn('other-net copper',planner.plan_rejections[0])

    def test_mask_only_npth_blocks_tracks_and_vias_on_inner_layers(self):
        pad=self.pad('SIGNAL',22,20)
        hole=self.pad('HOLE',23,20);hole.SetAttribute(p.PAD_ATTRIB_NPTH)
        hole.SetSize(self.pos(.6,.6));hole.SetDrillSize(self.pos(.6,.6))
        layers=p.LSET();layers.AddLayer(p.F_Mask);layers.AddLayer(p.B_Mask);hole.SetLayerSet(layers)
        planner=FanoutPlanner(self.board,p,dict(pattern='Radial outward',net_filter='SIGNAL',add_vias=False,width=.15,clearance=.1,length=1))
        self.assertFalse(planner._plan());self.assertIn('non-plated hole clearance',planner.plan_rejections[0])
        self.assertTrue(planner._copper_hits(hole,p.In1_Cu,self.pos(23,20),self.pos(23,20),p.FromMM(.1)))


if __name__=='__main__':unittest.main()
