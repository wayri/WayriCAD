"""Return-reference checks must inspect complete filled copper corridors."""
import unittest

from signal_integrity_advisor_plugin.return_path import analysis


class ReturnPolygonTests(unittest.TestCase):
    def region(self,holes=()):
        return analysis.ReferenceRegion('GND','In1.Cu',(0,0,10,10),((0,0),(10,0),(10,10),(0,10)),holes)

    def test_void_away_from_segment_midpoint_is_detected(self):
        region=self.region((((2,4),(3,4),(3,6),(2,6)),))
        trace=analysis.CopperSegment('N','F.Cu',(1,5),(9,5),.2)
        self.assertTrue(region.contains((5,5)))
        self.assertFalse(region.covers(trace))

    def test_small_hole_inside_wide_trace_corridor_is_detected(self):
        region=self.region((((4.9,4.98),(5.1,4.98),(5.1,5.02),(4.9,5.02)),))
        self.assertFalse(region.covers(analysis.CopperSegment('N','F.Cu',(1,5),(9,5),.5)))
        self.assertTrue(region.covers(analysis.CopperSegment('N','F.Cu',(1,7),(9,7),.5)))

    def test_nonadjacent_reference_does_not_hide_missing_adjacent_plane(self):
        region=analysis.ReferenceRegion('GND','B.Cu',(0,0,10,10))
        result=analysis.ReturnPathAnalyzer().audit([analysis.CopperSegment('N','F.Cu',(1,5),(9,5),.2)],[],[region],layer_order=['F.Cu','In1.Cu','In2.Cu','B.Cu'])
        self.assertTrue(any(f.check=='Reference-plane coverage' for f in result.findings))

    def test_return_via_must_cover_signal_transition_layers(self):
        vias=[analysis.ViaPoint('N',(5,5),('F.Cu','B.Cu')),analysis.ViaPoint('GND',(5.1,5),('F.Cu','In1.Cu'))]
        result=analysis.ReturnPathAnalyzer().audit([],vias,[])
        self.assertTrue(any(f.check=='Layer transition return via' for f in result.findings))

    def test_layer_crossing_is_not_a_branch_node(self):
        traces=[analysis.CopperSegment('N','F.Cu',(-10,0),(0,0),.2),analysis.CopperSegment('N','F.Cu',(0,0),(10,0),.2),
                analysis.CopperSegment('N','B.Cu',(0,0),(0,10),.2)]
        result=analysis.ReturnPathAnalyzer().audit(traces,[],[])
        self.assertFalse(any(f.check=='Possible routed stub' for f in result.findings))

    def test_mate_distance_uses_nearest_copper_not_remote_midpoint(self):
        traces=[analysis.CopperSegment('PAIR_P','F.Cu',(1,1),(2,1),.2),analysis.CopperSegment('PAIR_N','F.Cu',(0,1.3),(20,1.3),.2)]
        result=analysis.ReturnPathAnalyzer().audit(traces,[],[self.region()])
        self.assertFalse(any(f.check=='Differential-pair uncoupling' for f in result.findings))


if __name__=='__main__':unittest.main()
